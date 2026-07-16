"""Phase 5: conversation archive/mute + user block/report tables

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa


revision = "o9p0q1r2s3t4"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("archived_by_customer", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversation", sa.Column("archived_by_contractor", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversation", sa.Column("muted_by_customer", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversation", sa.Column("muted_by_contractor", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "userblock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blocker_id", sa.Integer(), nullable=False),
        sa.Column("blocked_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blocker_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["blocked_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_userblock_blocker_id", "userblock", ["blocker_id"])
    op.create_index("ix_userblock_blocked_id", "userblock", ["blocked_id"])

    op.create_table(
        "userreport",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reported_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("details", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["reported_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_userreport_reporter_id", "userreport", ["reporter_id"])
    op.create_index("ix_userreport_reported_id", "userreport", ["reported_id"])


def downgrade() -> None:
    op.drop_index("ix_userreport_reported_id", table_name="userreport")
    op.drop_index("ix_userreport_reporter_id", table_name="userreport")
    op.drop_table("userreport")
    op.drop_index("ix_userblock_blocked_id", table_name="userblock")
    op.drop_index("ix_userblock_blocker_id", table_name="userblock")
    op.drop_table("userblock")
    op.drop_column("conversation", "muted_by_contractor")
    op.drop_column("conversation", "muted_by_customer")
    op.drop_column("conversation", "archived_by_contractor")
    op.drop_column("conversation", "archived_by_customer")
