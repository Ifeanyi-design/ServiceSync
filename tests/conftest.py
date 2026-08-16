import os

# ── Offline test defaults ────────────────────────────────────────────────────
# The repo's CI expects Postgres; for local runs we use a throwaway sqlite file
# so the suite runs with zero external services. Override DATABASE_URL to point
# at Postgres in CI if desired.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_servicesync.db")
os.environ.setdefault(
    "SECRET_KEY", "test-secret-key-must-be-at-least-32-bytes-long-xxxxxxxx"
)
os.environ.setdefault("AI_PROVIDER", "ollama")
os.environ.setdefault("DEMO_MODE", "True")

import pytest
import pytest_asyncio

pytest_plugins = ("pytest_asyncio",)


@pytest_asyncio.fixture(autouse=True)
async def _db_schema():
    """Create a fresh schema before each test and tear it down after.

    Keeps every test isolated without needing migrations or an external DB.

    The models target Postgres (e.g. JSONB on the audit log). For the local
    sqlite test DB we swap JSONB -> JSON so ``create_all`` compiles.
    """
    from sqlmodel import SQLModel
    from app.core.database import engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON

    # Ensure every model (incl. the audit log) is registered before patching.
    import app.models.all_models  # noqa: F401
    import app.models.audit_log  # noqa: F401

    for table in SQLModel.metadata.tables.values():
        for col in table.columns.values():
            if isinstance(col.type, JSONB):
                col.type = JSON()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    # The in-memory rate limiter (RateLimitMiddleware) is process-global and keys
    # every TestClient request by the same IP ("testclient"), so its counters
    # otherwise accumulate across tests and trip 429s once the suite exceeds the
    # per-window cap. Reset it per test so each test starts clean.
    try:
        from app.main import RateLimitMiddleware
        RateLimitMiddleware._hits.clear()
    except Exception:
        pass
    yield
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
