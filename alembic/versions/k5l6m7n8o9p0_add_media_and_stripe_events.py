"""add chat attachments, user media, stripe events

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import String, JSON, DateTime, Boolean

revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("directmessage", sa.Column("attachment_url", String(), nullable=True))
    op.add_column("directmessage", sa.Column("attachment_type", String(), nullable=True))
    op.add_column("user", sa.Column("avatar_url", String(), nullable=True))
    op.add_column("user", sa.Column("cover_url", String(), nullable=True))

    op.create_table(
        "stripeevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stripe_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("payload", JSON(), nullable=False),
        sa.Column("created_at", DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stripeevent_stripe_event_id", "stripeevent", ["stripe_event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_stripeevent_stripe_event_id", table_name="stripeevent")
    op.drop_table("stripeevent")
    op.drop_column("user", "cover_url")
    op.drop_column("user", "avatar_url")
    op.drop_column("directmessage", "attachment_type")
    op.drop_column("directmessage", "attachment_url")
