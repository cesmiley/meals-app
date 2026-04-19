from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .repository import fetch_inventory_map, fetch_recipes_with_ingredients, staple_targets


@dataclass
class PlannedMeal:
    meal_date: date
    meal_index: int
    recipe_id: int | None
    recipe_title: str | None
    servings: int
    is_leftover: bool


@dataclass
class PlanOption:
    score: float
    entries: list[PlannedMeal]
    grocery_list: list[dict]


def generate_plan_options(request) -> list[PlanOption]:
    inventory_map = fetch_inventory_map()
    recipes = fetch_recipes_with_ingredients()
    if not recipes:
        return []

    options: list[PlanOption] = []
    for i in range(request.options):
        seed = 101 + i * 17
        option = build_option(request, recipes, inventory_map, seed)
        options.append(option)

    options.sort(key=lambda o: o.score, reverse=True)
    return options


def build_option(request, recipes: list[dict], inventory_map: dict[str, list[dict]], seed: int) -> PlanOption:
    rng = random.Random(seed)

    slots = []
    for day in range(request.days):
        d = request.start_date + timedelta(days=day)
        for meal_index in range(request.meals_per_person_per_day):
            slots.append((d, meal_index))

    entries: list[PlannedMeal] = []
    leftover_servings = 0
    used_recipe_ids: set[int] = set()

    for slot in slots:
        d, meal_index = slot

        if request.include_leftovers and leftover_servings >= request.people:
            leftover_servings -= request.people
            entries.append(
                PlannedMeal(
                    meal_date=d,
                    meal_index=meal_index,
                    recipe_id=None,
                    recipe_title="Leftovers",
                    servings=request.people,
                    is_leftover=True,
                )
            )
            continue

        available = [r for r in recipes if r["id"] not in used_recipe_ids]
        if not available:
            used_recipe_ids.clear()
            available = recipes

        scored_recipes = [(score_recipe(r, request.people, inventory_map, rng), r) for r in available]
        scored_recipes.sort(key=lambda x: x[0], reverse=True)

        candidates = scored_recipes[:min(5, len(scored_recipes))]
        raw_scores = [s for s, _ in candidates]
        min_s = min(raw_scores)
        weights = [s - min_s + 0.1 for s in raw_scores]
        _, best = candidates[rng.choices(range(len(candidates)), weights=weights)[0]]

        used_recipe_ids.add(best["id"])

        raw_produced = int(best.get("servings") or request.people)
        produced = min(max(request.people, raw_produced), request.people * 2)
        leftover_servings += max(0, produced - request.people)

        entries.append(
            PlannedMeal(
                meal_date=d,
                meal_index=meal_index,
                recipe_id=best["id"],
                recipe_title=best["title"],
                servings=request.people,
                is_leftover=False,
            )
        )

    grocery = build_grocery_list(entries, recipes, request.people, inventory_map)
    score = evaluate_plan(entries, grocery)

    return PlanOption(score=score, entries=entries, grocery_list=grocery)


def score_recipe(recipe: dict, people: int, inventory_map: dict[str, list[dict]], rng: random.Random) -> float:
    coverage = 0.0
    ingredients = recipe["ingredients"]

    for ing in ingredients:
        needed = float(ing.get("quantity") or 1.0)
        needed = needed * max(1.0, people / max(recipe.get("servings") or people, 1))

        inv_items = inventory_map.get(ing["normalized_item_name"], [])
        on_hand = sum(float(i.get("quantity_on_hand") or 0) for i in inv_items)
        part = min(on_hand / needed, 1.0) if needed > 0 else 1.0
        coverage += part

        for item in inv_items:
            if item.get("expires_on"):
                coverage += 0.05
            if item.get("is_staple") and item.get("stock_state") in {"low", "out"}:
                coverage -= 0.25

    base = coverage / max(len(ingredients), 1)
    favorite_bonus = 0.15 if recipe.get("favorite") else 0
    tried_bonus = 0.05 if recipe.get("tried") else 0
    random_tie_break = rng.random() * 0.15
    return base + favorite_bonus + tried_bonus + random_tie_break


def build_grocery_list(
    entries: list[PlannedMeal],
    recipes: list[dict],
    people: int,
    inventory_map: dict[str, list[dict]],
) -> list[dict]:
    recipe_map = {r["id"]: r for r in recipes}
    needed: dict[str, dict] = defaultdict(lambda: {"needed": 0.0, "unit": None, "name": None})

    for entry in entries:
        if entry.is_leftover or entry.recipe_id is None:
            continue
        recipe = recipe_map[entry.recipe_id]
        scale = people / max(recipe.get("servings") or people, 1)

        for ing in recipe["ingredients"]:
            key = ing["normalized_item_name"]
            needed[key]["needed"] += (float(ing.get("quantity") or 1.0) * scale)
            needed[key]["unit"] = needed[key]["unit"] or ing.get("unit")
            needed[key]["name"] = needed[key]["name"] or ing.get("item_name")

    lines: list[dict] = []
    staples = staple_targets()

    for key, payload in needed.items():
        inv_items = inventory_map.get(key, [])
        on_hand = sum(float(i.get("quantity_on_hand") or 0) for i in inv_items)
        to_buy = max(payload["needed"] - on_hand, 0)

        is_staple = key in staples
        reason = "required for recipes"

        if is_staple:
            min_qty = staples[key]["min_quantity"]
            projected = on_hand - payload["needed"]
            if projected < min_qty:
                top_up = min_qty - projected
                to_buy += max(top_up, 0)
                reason = "required for recipes + staple top-up"

        if to_buy > 0:
            lines.append(
                {
                    "item_name": payload["name"] or key,
                    "unit": payload["unit"] or infer_unit(inv_items),
                    "needed_quantity": round(payload["needed"], 2),
                    "on_hand_quantity": round(on_hand, 2),
                    "to_buy_quantity": round(to_buy, 2),
                    "is_staple": is_staple,
                    "reason": reason,
                }
            )

    for key, staple in staples.items():
        if key in needed:
            continue
        on_hand = staple["quantity_on_hand"]
        if on_hand < staple["min_quantity"]:
            lines.append(
                {
                    "item_name": staple["item_name"],
                    "unit": staple["unit"],
                    "needed_quantity": 0,
                    "on_hand_quantity": round(on_hand, 2),
                    "to_buy_quantity": round(staple["min_quantity"] - on_hand, 2),
                    "is_staple": True,
                    "reason": "staple below minimum",
                }
            )

    lines.sort(key=lambda x: (not x["is_staple"], -x["to_buy_quantity"], x["item_name"]))
    return lines


def infer_unit(inv_items: list[dict]) -> str | None:
    for item in inv_items:
        if item.get("unit"):
            return item["unit"]
    return None


def evaluate_plan(entries: list[PlannedMeal], grocery_list: list[dict]) -> float:
    leftover_utilization = sum(1 for e in entries if e.is_leftover) / max(len(entries), 1)
    grocery_cost_proxy = sum(line["to_buy_quantity"] for line in grocery_list)
    staple_shortage_penalty = sum(1 for line in grocery_list if line["is_staple"] and "minimum" in line["reason"])

    return round((leftover_utilization * 2.0) - (grocery_cost_proxy * 0.1) - (staple_shortage_penalty * 0.3), 3)


def customize_plan(people: int, raw_entries: list[dict]) -> PlanOption:
    inventory_map = fetch_inventory_map()
    recipes = fetch_recipes_with_ingredients()
    recipe_map = {r["id"]: r for r in recipes}

    entries: list[PlannedMeal] = []
    for raw in raw_entries:
        recipe_id = raw.get("recipe_id")
        recipe_title = recipe_map[recipe_id]["title"] if recipe_id in recipe_map else ("Leftovers" if raw.get("is_leftover") else None)
        entries.append(
            PlannedMeal(
                meal_date=raw["meal_date"],
                meal_index=raw["meal_index"],
                recipe_id=recipe_id,
                recipe_title=recipe_title,
                servings=raw["servings"],
                is_leftover=bool(raw.get("is_leftover")),
            )
        )

    grocery = build_grocery_list(entries, recipes, people, inventory_map)
    score = evaluate_plan(entries, grocery)
    return PlanOption(score=score, entries=entries, grocery_list=grocery)
