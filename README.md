# Meal Planner MVP

Backend API for:
- Pantry/fridge/freezer inventory with staple tracking and `stock_state`
- Recipe index with URL inbox import (attempts to parse ingredients + quantities)
- Recipe labels/tags (`under-30-mins`, `one-pot`, `no-cook`, etc.)
- Meal plan option generation that considers on-hand inventory, staple minimums, and leftovers
- Grocery list generation from plan gaps + staple top-ups

## Stock field naming
Use `stock_state` for each inventory item. Allowed values:
- `stocked`
- `low`
- `out`

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Uses local SQLite by default. In hosted environments, set `DATABASE_URL` to use Postgres.

## Deploy To Render (Free Tier)
This repo now includes [render.yaml](/home/cesmiley/Projects/meal-planner/render.yaml) for one-click blueprint deploy.

1. Push this project to GitHub.
2. In Render, select `New` -> `Blueprint` and choose your repo.
3. Render will provision:
   - web service: `meal-planner-api`
   - Postgres database: `meal-planner-db`
4. Deploy and open:
   - `GET /health` to confirm app is live
   - `/docs` for interactive API testing

Render sets `DATABASE_URL` from the Postgres service automatically via `render.yaml`.

If you deploy manually without blueprint:
- Create a Postgres instance in Render.
- Create a Python web service from this repo.
- Set env var `DATABASE_URL` to the Render Postgres connection string.
- Start command:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Key Endpoints
- `GET /` (web UI)
- `POST /inventory/items`
- `GET /inventory/items?location=fridge&staples_only=true`
- `PATCH /inventory/items/{item_id}`
- `DELETE /inventory/items/{item_id}`
- `POST /recipes`
- `POST /recipes/inbox/import`
- `GET /recipes?favorite=true&tags=under-30-mins`
- `POST /plans/generate`
- `POST /plans/customize`

## Example: Add inventory item
```bash
curl -X POST http://127.0.0.1:8000/inventory/items \
  -H "content-type: application/json" \
  -d '{
    "name": "Chicken Breast",
    "location": "freezer",
    "quantity_on_hand": 4,
    "unit": "lb",
    "is_staple": true,
    "stock_state": "low",
    "min_quantity": 6,
    "price_per_unit": 4.99
  }'
```

## Example: Import recipe by URL (recipe inbox)
```bash
curl -X POST http://127.0.0.1:8000/recipes/inbox/import \
  -H "content-type: application/json" \
  -d '{"url":"https://example.com/my-recipe"}'
```

## Example: Create recipe manually with tags
```bash
curl -X POST http://127.0.0.1:8000/recipes \
  -H "content-type: application/json" \
  -d '{
    "title": "One Pan Lemon Chicken",
    "tried": true,
    "favorite": true,
    "servings": 4,
    "estimated_minutes": 25,
    "tags": ["under-30-mins", "one-pot"],
    "ingredients": [
      {"item_name":"chicken breast","quantity":2,"unit":"lb"},
      {"item_name":"lemon","quantity":2,"unit":null},
      {"item_name":"olive oil","quantity":2,"unit":"tbsp"}
    ]
  }'
```

## Example: Generate meal plan options + grocery list
```bash
curl -X POST http://127.0.0.1:8000/plans/generate \
  -H "content-type: application/json" \
  -d '{
    "people": 2,
    "days": 7,
    "meals_per_person_per_day": 2,
    "start_date": "2026-04-06",
    "include_leftovers": true,
    "options": 3
  }'
```

## Example: Customize a plan and regenerate grocery list
```bash
curl -X POST http://127.0.0.1:8000/plans/customize \
  -H "content-type: application/json" \
  -d '{
    "people": 2,
    "entries": [
      {"meal_date":"2026-04-06","meal_index":0,"recipe_id":1,"is_leftover":false,"servings":2},
      {"meal_date":"2026-04-06","meal_index":1,"recipe_id":null,"is_leftover":true,"servings":2}
    ]
  }'
```

## Notes
- Import parsing uses `application/ld+json` recipe metadata when available.
- Quantity/unit normalization is lightweight; a production setup should add robust unit conversion.
- The planner uses heuristics for cost/waste optimization and produces multiple scored options.
- SQLite is for local development; production hosting should use Postgres (`DATABASE_URL`).

## Web UI
- Local: `http://127.0.0.1:8000/`
- Render: `https://meal-planner-api-vgfz.onrender.com/`
- Workflow:
  1. Add inventory items (including staples and stock state).
  2. Add/import recipes.
  3. Use **Plan This Week** to generate options and grocery lists.
