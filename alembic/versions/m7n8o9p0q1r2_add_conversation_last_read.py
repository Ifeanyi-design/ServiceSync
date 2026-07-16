"""add conversation last_read_at fields for unread tracking

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("last_read_at_customer", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("last_read_at_contractor", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation", "last_read_at_contractor")
    op.drop_column("conversation", "last_read_at_customer")
