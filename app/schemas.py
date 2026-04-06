from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


StockState = Literal["stocked", "low", "out"]
Location = Literal["fridge", "pantry", "freezer"]


class InventoryItemCreate(BaseModel):
    name: str
    location: Location
    quantity_on_hand: float = 0
    unit: str | None = None
    is_staple: bool = False
    stock_state: StockState = "stocked"
    min_quantity: float = 0
    price_per_unit: float | None = None
    expires_on: date | None = None


class InventoryItemUpdate(BaseModel):
    name: str | None = None
    location: Location | None = None
    quantity_on_hand: float | None = None
    unit: str | None = None
    is_staple: bool | None = None
    stock_state: StockState | None = None
    min_quantity: float | None = None
    price_per_unit: float | None = None
    expires_on: date | None = None


class InventoryItemOut(BaseModel):
    id: int
    name: str
    location: Location
    quantity_on_hand: float
    unit: str | None
    is_staple: bool
    stock_state: StockState
    min_quantity: float
    price_per_unit: float | None
    expires_on: date | None


class RecipeIngredientIn(BaseModel):
    item_name: str
    quantity: float | None = None
    unit: str | None = None
    optional: bool = False


class RecipeCreate(BaseModel):
    title: str
    url: HttpUrl | None = None
    source: str | None = None
    tried: bool = False
    favorite: bool = False
    servings: int | None = None
    estimated_minutes: int | None = None
    tags: list[str] = Field(default_factory=list)
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)


class RecipeImportRequest(BaseModel):
    url: HttpUrl


class RecipeOut(BaseModel):
    id: int
    title: str
    url: str | None
    source: str | None
    tried: bool
    favorite: bool
    servings: int | None
    estimated_minutes: int | None
    parsed_ok: bool
    tags: list[str]
    ingredients: list[RecipeIngredientIn]


class MealPlanGenerateRequest(BaseModel):
    people: int = Field(gt=0)
    days: int = Field(gt=0, le=31)
    meals_per_person_per_day: int = Field(gt=0, le=4)
    start_date: date
    include_leftovers: bool = True
    options: int = Field(default=3, gt=0, le=5)


class MealPlanEntryOut(BaseModel):
    meal_date: date
    meal_index: int
    recipe_id: int | None
    recipe_title: str | None
    servings: int
    is_leftover: bool


class GroceryLineOut(BaseModel):
    item_name: str
    unit: str | None
    needed_quantity: float
    on_hand_quantity: float
    to_buy_quantity: float
    is_staple: bool
    reason: str


class MealPlanOptionOut(BaseModel):
    score: float
    entries: list[MealPlanEntryOut]
    grocery_list: list[GroceryLineOut]


class MealPlanGenerateResponse(BaseModel):
    options: list[MealPlanOptionOut]


class MealPlanCustomizeEntryIn(BaseModel):
    meal_date: date
    meal_index: int
    recipe_id: int | None = None
    is_leftover: bool = False
    servings: int = Field(gt=0)


class MealPlanCustomizeRequest(BaseModel):
    people: int = Field(gt=0)
    entries: list[MealPlanCustomizeEntryIn]
