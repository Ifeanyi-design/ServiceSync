"""add user notification_prefs and is_active

Revision ID: l6m7n8o9p0q1
Revises: 0a025696488b
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, Boolean

revision = "l6m7n8o9p0q1"
down_revision = "0a025696488b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("notification_prefs", JSON(), nullable=True))
    op.add_column("user", sa.Column("is_active", Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("user", "is_active")
    op.drop_column("user", "notification_prefs")
