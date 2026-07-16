"""add attachment_name to directmessage for original filenames

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "n8o9p0q1r2s3"
down_revision = "m7n8o9p0q1r2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("directmessage", sa.Column("attachment_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("directmessage", "attachment_name")
