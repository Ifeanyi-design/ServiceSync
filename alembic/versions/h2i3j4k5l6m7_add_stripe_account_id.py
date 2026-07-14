"""add stripe_account_id to user

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("stripe_account_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "stripe_account_id")
