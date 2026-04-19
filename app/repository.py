from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from .database import get_conn
from .schemas import InventoryItemCreate, InventoryItemUpdate, RecipeCreate


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


_QUALIFIER_STOPWORDS = {
    "fresh", "dried", "frozen", "canned", "sliced", "diced", "chopped",
    "minced", "ground", "whole", "large", "small", "medium", "organic",
    "packages", "package", "cans", "can", "oz", "lb", "lbs", "g", "ml",
    "creamy", "smooth", "chunky", "extra", "virgin", "light", "dark",
    "low", "fat", "sodium", "reduced", "unsalted", "salted",
}


def _core_tokens(name: str) -> frozenset[str]:
    """Strip parenthetical content, noise qualifiers, and digits; return remaining tokens."""
    name = re.sub(r"\([^)]*\)", "", name)
    return frozenset(
        t for t in name.split()
        if t not in _QUALIFIER_STOPWORDS and not t.isdigit() and len(t) > 2
    )


def resolve_inventory_key(query: str, mapping: dict) -> str | None:
    """Return the best matching key in mapping for query using exact then fuzzy token match."""
    if query in mapping:
        return query
    query_core = _core_tokens(query)
    if not query_core:
        return None
    best_key: str | None = None
    best_score = 0.0
    for key in mapping:
        key_core = _core_tokens(key)
        if not key_core:
            continue
        shared = query_core & key_core
        if not shared:
            continue
        if not (key_core <= query_core or query_core <= key_core):
            continue
        if not any(len(t) > 3 for t in shared):
            continue
        score = len(shared) / len(query_core | key_core)
        if score > best_score:
            best_score = score
            best_key = key
    return best_key


def fuzzy_inventory_lookup(query: str, inventory_map: dict[str, list[dict]]) -> list[dict]:
    key = resolve_inventory_key(query, inventory_map)
    return inventory_map[key] if key is not None else []


def create_inventory_item(data: InventoryItemCreate) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO inventory_items
            (name, normalized_name, location, quantity_on_hand, unit, is_staple, stock_state,
             min_quantity, price_per_unit, expires_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                data.name,
                normalize_name(data.name),
                data.location,
                data.quantity_on_hand,
                data.unit,
                int(data.is_staple),
                data.stock_state,
                data.min_quantity,
                data.price_per_unit,
                data.expires_on.isoformat() if data.expires_on else None,
            ),
        )
        item_id = cur.fetchone()["id"]
    return get_inventory_item(item_id)


def list_inventory(location: str | None = None, staples_only: bool = False) -> list[dict]:
    query = "SELECT * FROM inventory_items WHERE 1=1"
    params: list[object] = []
    if location:
        query += " AND location = ?"
        params.append(location)
    if staples_only:
        query += " AND is_staple = 1"
    query += " ORDER BY name"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_inventory_dict(r) for r in rows]


def get_inventory_item(item_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
    return row_to_inventory_dict(row) if row else None


def update_inventory_item(item_id: int, data: InventoryItemUpdate) -> dict | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return get_inventory_item(item_id)

    if "name" in fields:
        fields["normalized_name"] = normalize_name(fields["name"])
    if "expires_on" in fields and isinstance(fields["expires_on"], date):
        fields["expires_on"] = fields["expires_on"].isoformat()

    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    values.append(item_id)

    with get_conn() as conn:
        conn.execute(f"UPDATE inventory_items SET {assignments} WHERE id = ?", values)
    return get_inventory_item(item_id)


def delete_inventory_item(item_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
    return True


def row_to_inventory_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "location": row["location"],
        "quantity_on_hand": row["quantity_on_hand"],
        "unit": row["unit"],
        "is_staple": bool(row["is_staple"]),
        "stock_state": row["stock_state"],
        "min_quantity": row["min_quantity"] or 0,
        "price_per_unit": row["price_per_unit"],
        "expires_on": row["expires_on"],
    }


def create_recipe(data: RecipeCreate, parsed_ok: bool = False) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO recipes (title, url, source, tried, favorite, servings, estimated_minutes, parsed_ok)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                data.title,
                str(data.url) if data.url else None,
                data.source,
                int(data.tried),
                int(data.favorite),
                data.servings,
                data.estimated_minutes,
                int(parsed_ok),
            ),
        )
        recipe_id = cur.fetchone()["id"]

        for ingredient in data.ingredients:
            conn.execute(
                """
                INSERT INTO recipe_ingredients (recipe_id, item_name, normalized_item_name, quantity, unit, optional)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    recipe_id,
                    ingredient.item_name,
                    normalize_name(ingredient.item_name),
                    ingredient.quantity,
                    ingredient.unit,
                    int(ingredient.optional),
                ),
            )

        for tag in {t.strip().lower() for t in data.tags if t.strip()}:
            tag_id = upsert_tag(conn, tag)
            conn.execute(
                """
                INSERT INTO recipe_tags (recipe_id, tag_id)
                VALUES (?, ?)
                ON CONFLICT (recipe_id, tag_id) DO NOTHING
                """,
                (recipe_id, tag_id),
            )

    return get_recipe(recipe_id)


def upsert_tag(conn, name: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO tags (name)
        VALUES (?)
        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (name,),
    )
    return cur.fetchone()["id"]


def list_recipes(
    tags: list[str] | None = None,
    tried: bool | None = None,
    favorite: bool | None = None,
) -> list[dict]:
    with get_conn() as conn:
        query = "SELECT * FROM recipes WHERE 1=1"
        params: list[object] = []
        if tried is not None:
            query += " AND tried = ?"
            params.append(int(tried))
        if favorite is not None:
            query += " AND favorite = ?"
            params.append(int(favorite))
        rows = conn.execute(query + " ORDER BY created_at DESC", params).fetchall()

        result = []
        for row in rows:
            recipe = get_recipe(row["id"], conn)
            if not recipe:
                continue
            if tags:
                tag_set = {t.strip().lower() for t in tags}
                if not tag_set.issubset(set(recipe["tags"])):
                    continue
            result.append(recipe)
        return result


def get_recipe(recipe_id: int, conn=None) -> dict | None:
    owned_conn = False
    if conn is None:
        owned_conn = True
        cm = get_conn()
        conn = cm.__enter__()

    try:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not row:
            return None

        ingredient_rows = conn.execute(
            "SELECT item_name, quantity, unit, optional FROM recipe_ingredients WHERE recipe_id = ?",
            (recipe_id,),
        ).fetchall()
        tag_rows = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN recipe_tags rt ON rt.tag_id = t.id
            WHERE rt.recipe_id = ?
            ORDER BY t.name
            """,
            (recipe_id,),
        ).fetchall()

        return {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "tried": bool(row["tried"]),
            "favorite": bool(row["favorite"]),
            "servings": row["servings"],
            "estimated_minutes": row["estimated_minutes"],
            "parsed_ok": bool(row["parsed_ok"]),
            "tags": [r["name"] for r in tag_rows],
            "ingredients": [
                {
                    "item_name": r["item_name"],
                    "quantity": r["quantity"],
                    "unit": r["unit"],
                    "optional": bool(r["optional"]),
                }
                for r in ingredient_rows
            ],
        }
    finally:
        if owned_conn:
            cm.__exit__(None, None, None)


def fetch_inventory_map() -> dict[str, list[dict]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM inventory_items").fetchall()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["normalized_name"]].append(row_to_inventory_dict(row))
    return grouped


def fetch_recipes_with_ingredients() -> list[dict]:
    with get_conn() as conn:
        recipe_rows = conn.execute("SELECT * FROM recipes ORDER BY favorite DESC, created_at DESC").fetchall()
        recipes = []
        for row in recipe_rows:
            ingredient_rows = conn.execute(
                """
                SELECT item_name, normalized_item_name, quantity, unit, optional
                FROM recipe_ingredients
                WHERE recipe_id = ?
                """,
                (row["id"],),
            ).fetchall()
            if not ingredient_rows:
                continue
            tags = conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN recipe_tags rt ON rt.tag_id = t.id
                WHERE rt.recipe_id = ?
                """,
                (row["id"],),
            ).fetchall()
            recipes.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "servings": row["servings"] or 2,
                    "favorite": bool(row["favorite"]),
                    "tried": bool(row["tried"]),
                    "ingredients": [dict(r) for r in ingredient_rows],
                    "tags": [r["name"] for r in tags],
                }
            )
    return recipes


def save_meal_plan(request, entries: list[dict]) -> int:
    end_date = request.start_date.fromordinal(request.start_date.toordinal() + request.days - 1)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO meal_plans (start_date, end_date, people, meals_per_person_per_day, include_leftovers)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                request.start_date.isoformat(),
                end_date.isoformat(),
                request.people,
                request.meals_per_person_per_day,
                int(request.include_leftovers),
            ),
        )
        plan_id = cur.fetchone()["id"]

        for e in entries:
            conn.execute(
                """
                INSERT INTO meal_plan_entries
                (meal_plan_id, meal_date, meal_index, recipe_id, servings, is_leftover, source_entry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    e["meal_date"],
                    e["meal_index"],
                    e.get("recipe_id"),
                    e["servings"],
                    int(e["is_leftover"]),
                    e.get("source_entry_id"),
                ),
            )
    return plan_id


def ingredient_templates_by_name() -> dict[str, tuple[str, str | None]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT normalized_name, name, unit
            FROM inventory_items
            ORDER BY id DESC
            """
        ).fetchall()
    templates: dict[str, tuple[str, str | None]] = {}
    for r in rows:
        templates[r["normalized_name"]] = (r["name"], r["unit"])
    return templates


def staple_targets() -> dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT normalized_name, name, unit, min_quantity, quantity_on_hand
            FROM inventory_items
            WHERE is_staple = 1
            """
        ).fetchall()

    result: dict[str, dict] = {}
    for r in rows:
        prior = result.get(r["normalized_name"])
        if prior is None:
            result[r["normalized_name"]] = {
                "item_name": r["name"],
                "unit": r["unit"],
                "min_quantity": r["min_quantity"] or 0,
                "quantity_on_hand": r["quantity_on_hand"] or 0,
            }
        else:
            prior["quantity_on_hand"] += r["quantity_on_hand"] or 0
            prior["min_quantity"] = max(prior["min_quantity"], r["min_quantity"] or 0)
    return result
