from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fractions import Fraction
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .schemas import RecipeIngredientIn

UNITS = {
    "tsp",
    "teaspoon",
    "teaspoons",
    "tbsp",
    "tablespoon",
    "tablespoons",
    "cup",
    "cups",
    "oz",
    "ounce",
    "ounces",
    "lb",
    "pound",
    "pounds",
    "g",
    "gram",
    "grams",
    "kg",
    "ml",
    "l",
    "clove",
    "cloves",
    "can",
    "cans",
}


@dataclass
class ImportedRecipe:
    title: str
    source: str
    servings: int | None
    estimated_minutes: int | None
    ingredients: list[RecipeIngredientIn]
    parsed_ok: bool


class JSONLDScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_jsonld = False
        self.payloads: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if attr_map.get("type", "").lower() == "application/ld+json":
            self.in_jsonld = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_jsonld = False

    def handle_data(self, data):
        if self.in_jsonld and data.strip():
            self.payloads.append(data.strip())


def import_recipe_from_url(url: str) -> ImportedRecipe:
    req = Request(url, headers={"User-Agent": "MealPlannerBot/1.0"})
    with urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    parser = JSONLDScriptParser()
    parser.feed(html)

    for payload in parser.payloads:
        candidate = parse_recipe_payload(payload)
        if candidate:
            return candidate

    return ImportedRecipe(
        title=f"Imported from {urlparse(url).netloc}",
        source=urlparse(url).netloc,
        servings=None,
        estimated_minutes=None,
        ingredients=[],
        parsed_ok=False,
    )


def parse_recipe_payload(payload: str) -> ImportedRecipe | None:
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None

    recipe_obj = find_recipe_object(obj)
    if not recipe_obj:
        return None

    title = str(recipe_obj.get("name") or "Imported recipe").strip()
    source = ""
    if isinstance(recipe_obj.get("author"), dict):
        source = str(recipe_obj["author"].get("name") or "")

    ingredients_raw = recipe_obj.get("recipeIngredient") or []
    ingredients: list[RecipeIngredientIn] = []
    for line in ingredients_raw:
        parsed = parse_ingredient_line(str(line))
        ingredients.append(parsed)

    servings = parse_int(recipe_obj.get("recipeYield"))
    minutes = parse_duration_minutes(recipe_obj.get("totalTime"))

    return ImportedRecipe(
        title=title,
        source=source or "web",
        servings=servings,
        estimated_minutes=minutes,
        ingredients=ingredients,
        parsed_ok=True,
    )


def find_recipe_object(data):
    if isinstance(data, dict):
        typ = data.get("@type")
        if is_recipe_type(typ):
            return data
        if "@graph" in data:
            found = find_recipe_object(data["@graph"])
            if found:
                return found
        for value in data.values():
            found = find_recipe_object(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_recipe_object(item)
            if found:
                return found
    return None


def is_recipe_type(value) -> bool:
    if isinstance(value, str):
        return value.lower() == "recipe"
    if isinstance(value, list):
        return any(isinstance(v, str) and v.lower() == "recipe" for v in value)
    return False


def parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    match = re.search(r"\d+", text)
    if match:
        return int(match.group(0))
    return None


def parse_duration_minutes(value) -> int | None:
    if not value:
        return None
    raw = str(value)
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", raw)
    if not match:
        return parse_int(raw)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


def parse_ingredient_line(line: str) -> RecipeIngredientIn:
    raw = line.strip()
    optional = "optional" in raw.lower()

    tokens = raw.split()
    quantity = None
    unit = None

    if tokens:
        quantity = parse_quantity(tokens[0])
        consumed = 1 if quantity is not None else 0

        if consumed == 1 and len(tokens) > 1:
            combo_quantity = parse_quantity(f"{tokens[0]} {tokens[1]}")
            if combo_quantity is not None:
                quantity = combo_quantity
                consumed = 2

        if consumed < len(tokens):
            unit_candidate = tokens[consumed].lower().strip(",")
            if unit_candidate in UNITS:
                unit = unit_candidate
                consumed += 1

        item_name = " ".join(tokens[consumed:]).strip(" ,") if consumed else raw
    else:
        item_name = raw

    return RecipeIngredientIn(
        item_name=item_name or raw,
        quantity=quantity,
        unit=unit,
        optional=optional,
    )


def parse_quantity(text: str) -> float | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    unicode_fractions = {
        "¼": "1/4",
        "½": "1/2",
        "¾": "3/4",
        "⅓": "1/3",
        "⅔": "2/3",
    }
    for key, value in unicode_fractions.items():
        cleaned = cleaned.replace(key, value)

    parts = cleaned.split()
    try:
        if len(parts) == 2 and "/" in parts[1]:
            return float(parts[0]) + float(Fraction(parts[1]))
        if "/" in cleaned:
            return float(Fraction(cleaned))
        return float(cleaned)
    except Exception:
        return None
