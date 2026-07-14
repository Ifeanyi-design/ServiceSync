"""add subscription fields to user

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("subscription_tier", sa.String(), nullable=False, server_default="free"))
    op.add_column("user", sa.Column("subscription_status", sa.String(), nullable=False, server_default="active"))
    op.add_column("user", sa.Column("trial_ends_at", sa.DateTime(), nullable=True))
    op.add_column("user", sa.Column("subscription_started_at", sa.DateTime(), nullable=True))
    op.add_column("user", sa.Column("subscription_ends_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "subscription_ends_at")
    op.drop_column("user", "subscription_started_at")
    op.drop_column("user", "trial_ends_at")
    op.drop_column("user", "subscription_status")
    op.drop_column("user", "subscription_tier")
