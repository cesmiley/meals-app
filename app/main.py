from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .database import init_db
from .planner import customize_plan, generate_plan_options
from .recipe_import import import_recipe_from_url
from .repository import (
    create_inventory_item,
    create_recipe,
    get_inventory_item,
    list_inventory,
    list_recipes,
    update_inventory_item,
)
from .schemas import (
    InventoryItemCreate,
    InventoryItemOut,
    InventoryItemUpdate,
    MealPlanCustomizeRequest,
    MealPlanEntryOut,
    MealPlanGenerateRequest,
    MealPlanGenerateResponse,
    MealPlanOptionOut,
    RecipeCreate,
    RecipeImportRequest,
    RecipeOut,
)

app = FastAPI(title="Meal Planner API", version="0.1.0")
UI_INDEX = Path(__file__).parent / "static" / "index.html"


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(UI_INDEX)


@app.post("/inventory/items", response_model=InventoryItemOut)
def add_inventory_item(payload: InventoryItemCreate):
    return create_inventory_item(payload)


@app.get("/inventory/items", response_model=list[InventoryItemOut])
def get_inventory_items(
    location: str | None = Query(default=None),
    staples_only: bool = Query(default=False),
):
    return list_inventory(location=location, staples_only=staples_only)


@app.patch("/inventory/items/{item_id}", response_model=InventoryItemOut)
def patch_inventory_item(item_id: int, payload: InventoryItemUpdate):
    if not get_inventory_item(item_id):
        raise HTTPException(status_code=404, detail="Inventory item not found")
    updated = update_inventory_item(item_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return updated


@app.post("/recipes", response_model=RecipeOut)
def add_recipe(payload: RecipeCreate):
    return create_recipe(payload, parsed_ok=False)


@app.post("/recipes/inbox/import", response_model=RecipeOut)
def import_recipe(payload: RecipeImportRequest):
    imported = import_recipe_from_url(str(payload.url))
    record = RecipeCreate(
        title=imported.title,
        url=str(payload.url),
        source=imported.source,
        servings=imported.servings,
        estimated_minutes=imported.estimated_minutes,
        ingredients=imported.ingredients,
    )
    return create_recipe(record, parsed_ok=imported.parsed_ok)


@app.get("/recipes", response_model=list[RecipeOut])
def get_recipes(
    tried: bool | None = Query(default=None),
    favorite: bool | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
):
    return list_recipes(tags=tags, tried=tried, favorite=favorite)


@app.post("/plans/generate", response_model=MealPlanGenerateResponse)
def generate_meal_plans(payload: MealPlanGenerateRequest):
    options = generate_plan_options(payload)

    response_options = []
    for option in options:
        response_options.append(
            MealPlanOptionOut(
                score=option.score,
                entries=[
                    MealPlanEntryOut(
                        meal_date=e.meal_date,
                        meal_index=e.meal_index,
                        recipe_id=e.recipe_id,
                        recipe_title=e.recipe_title,
                        servings=e.servings,
                        is_leftover=e.is_leftover,
                    )
                    for e in option.entries
                ],
                grocery_list=option.grocery_list,
            )
        )

    return MealPlanGenerateResponse(options=response_options)


@app.post("/plans/customize", response_model=MealPlanOptionOut)
def customize_meal_plan(payload: MealPlanCustomizeRequest):
    option = customize_plan(
        people=payload.people,
        raw_entries=[entry.model_dump() for entry in payload.entries],
    )
    return MealPlanOptionOut(
        score=option.score,
        entries=[
            MealPlanEntryOut(
                meal_date=e.meal_date,
                meal_index=e.meal_index,
                recipe_id=e.recipe_id,
                recipe_title=e.recipe_title,
                servings=e.servings,
                is_leftover=e.is_leftover,
            )
            for e in option.entries
        ],
        grocery_list=option.grocery_list,
    )
