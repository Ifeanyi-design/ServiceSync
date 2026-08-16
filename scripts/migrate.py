"""Idempotent schema migration for new Phase 1 / Phase 5 models.

Why this exists: SQLModel ``create_all`` only creates *missing* tables — it does
not add new columns to tables that already exist in a deployed database. The app
gained new columns (``User.specialties``, ``Job.category``, ``Job.brief``,
``Job.matched_contractor_ids``) and new tables (``Supplier``, ``Product``,
``JobMaterial``, ``MaterialOrder``) after the original schema shipped.

This script is dialect-agnostic (works on sqlite dev DBs and Postgres in prod):
- ``CREATE TABLE IF NOT EXISTS`` for every model table.
- ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` for any column missing from an
  existing table.

Run with:  python scripts/migrate.py   (reads DATABASE_URL from the env).
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlmodel import SQLModel

import app.models.all_models  # noqa: F401  (registers all models)
import app.models.audit_log  # noqa: F401

from app.core.database import engine


async def migrate() -> None:
    # sqlite can't render Postgres JSONB; swap it for JSON on that dialect only.
    if engine.dialect.name == "sqlite":
        for table in SQLModel.metadata.tables.values():
            for col in table.columns.values():
                if isinstance(col.type, JSONB):
                    col.type = JSON()

    async with engine.begin() as conn:
        def _sync(sync_conn):
            # 1) Create any tables that don't exist yet.
            SQLModel.metadata.create_all(sync_conn, checkfirst=True)

            # 2) Add any missing columns to tables that already exist.
            insp = inspect(sync_conn)
            existing_tables = set(insp.get_table_names())
            for table in SQLModel.metadata.tables.values():
                if table.name not in existing_tables:
                    continue
                db_cols = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in db_cols:
                        continue
                    type_sql = col.type.compile(dialect=engine.dialect)
                    null = "" if col.nullable else " NOT NULL"
                    stmt = text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS '
                        f'"{col.name}" {type_sql}{null}'
                    )
                    sync_conn.execute(stmt)
                    print(f"  + added column {table.name}.{col.name}")

        await conn.run_sync(_sync)
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
