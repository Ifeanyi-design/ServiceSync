"""CLI entrypoint for the idempotent schema migration.

The real logic lives in ``app.core.migrate`` so it can also be called from the
app startup and the seeder. Run with:  python scripts/migrate.py
"""
from app.core.migrate import run_migration_sync

if __name__ == "__main__":
    run_migration_sync()
