"""add boosted_until to user

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import DateTime

revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("boosted_until", DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "boosted_until")
