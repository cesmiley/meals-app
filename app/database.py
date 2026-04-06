from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DB_PATH = Path("meal_planner.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

SQLITE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS inventory_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  location TEXT NOT NULL CHECK(location IN ('fridge', 'pantry', 'freezer')),
  quantity_on_hand REAL NOT NULL DEFAULT 0,
  unit TEXT,
  is_staple INTEGER NOT NULL DEFAULT 0,
  stock_state TEXT NOT NULL DEFAULT 'stocked' CHECK(stock_state IN ('stocked', 'low', 'out')),
  min_quantity REAL DEFAULT 0,
  price_per_unit REAL,
  expires_on TEXT
);

CREATE INDEX IF NOT EXISTS idx_inventory_normalized_name ON inventory_items(normalized_name);
CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory_items(location);

CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT,
  source TEXT,
  tried INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0,
  servings INTEGER,
  estimated_minutes INTEGER,
  parsed_ok INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipe_id INTEGER NOT NULL,
  item_name TEXT NOT NULL,
  normalized_item_name TEXT NOT NULL,
  quantity REAL,
  unit TEXT,
  optional INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe ON recipe_ingredients(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_norm ON recipe_ingredients(normalized_item_name);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS recipe_tags (
  recipe_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL,
  PRIMARY KEY(recipe_id, tag_id),
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
  FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meal_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  people INTEGER NOT NULL,
  meals_per_person_per_day INTEGER NOT NULL,
  include_leftovers INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meal_plan_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  meal_plan_id INTEGER NOT NULL,
  meal_date TEXT NOT NULL,
  meal_index INTEGER NOT NULL,
  recipe_id INTEGER,
  servings INTEGER,
  is_leftover INTEGER NOT NULL DEFAULT 0,
  source_entry_id INTEGER,
  FOREIGN KEY(meal_plan_id) REFERENCES meal_plans(id) ON DELETE CASCADE,
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE SET NULL,
  FOREIGN KEY(source_entry_id) REFERENCES meal_plan_entries(id) ON DELETE SET NULL
);
"""

POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inventory_items (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  location TEXT NOT NULL CHECK(location IN ('fridge', 'pantry', 'freezer')),
  quantity_on_hand DOUBLE PRECISION NOT NULL DEFAULT 0,
  unit TEXT,
  is_staple INTEGER NOT NULL DEFAULT 0,
  stock_state TEXT NOT NULL DEFAULT 'stocked' CHECK(stock_state IN ('stocked', 'low', 'out')),
  min_quantity DOUBLE PRECISION DEFAULT 0,
  price_per_unit DOUBLE PRECISION,
  expires_on TEXT
);

CREATE INDEX IF NOT EXISTS idx_inventory_normalized_name ON inventory_items(normalized_name);
CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory_items(location);

CREATE TABLE IF NOT EXISTS recipes (
  id BIGSERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT,
  source TEXT,
  tried INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0,
  servings INTEGER,
  estimated_minutes INTEGER,
  parsed_ok INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
  id BIGSERIAL PRIMARY KEY,
  recipe_id BIGINT NOT NULL,
  item_name TEXT NOT NULL,
  normalized_item_name TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  unit TEXT,
  optional INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe ON recipe_ingredients(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_norm ON recipe_ingredients(normalized_item_name);

CREATE TABLE IF NOT EXISTS tags (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS recipe_tags (
  recipe_id BIGINT NOT NULL,
  tag_id BIGINT NOT NULL,
  PRIMARY KEY(recipe_id, tag_id),
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
  FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meal_plans (
  id BIGSERIAL PRIMARY KEY,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  people INTEGER NOT NULL,
  meals_per_person_per_day INTEGER NOT NULL,
  include_leftovers INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meal_plan_entries (
  id BIGSERIAL PRIMARY KEY,
  meal_plan_id BIGINT NOT NULL,
  meal_date TEXT NOT NULL,
  meal_index INTEGER NOT NULL,
  recipe_id BIGINT,
  servings INTEGER,
  is_leftover INTEGER NOT NULL DEFAULT 0,
  source_entry_id BIGINT,
  FOREIGN KEY(meal_plan_id) REFERENCES meal_plans(id) ON DELETE CASCADE,
  FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE SET NULL,
  FOREIGN KEY(source_entry_id) REFERENCES meal_plan_entries(id) ON DELETE SET NULL
);
"""


def _adapt_query(query: str) -> str:
    if IS_POSTGRES:
        return query.replace("?", "%s")
    return query


class DBCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class DBConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params=None):
        if params is None:
            params = ()
        cur = self._conn.execute(_adapt_query(query), params)
        return DBCursor(cur)

    def executescript(self, script: str):
        if IS_POSTGRES:
            for statement in script.split(";"):
                stmt = statement.strip()
                if stmt:
                    self._conn.execute(stmt)
            return
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@contextmanager
def get_conn():
    if IS_POSTGRES:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    wrapped = DBConnection(conn)
    try:
        if not IS_POSTGRES:
            wrapped.execute("PRAGMA foreign_keys = ON;")
        yield wrapped
        wrapped.commit()
    except Exception:
        wrapped.rollback()
        raise
    finally:
        wrapped.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(POSTGRES_SCHEMA_SQL if IS_POSTGRES else SQLITE_SCHEMA_SQL)
