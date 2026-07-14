"""transaction flow: escrow funding, job lifecycle, contractor wallet

Revision ID: g1h2i3j4k5l6
Revises: f7a8b9c0d1e2
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Numeric

revision = "g1h2i3j4k5l6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Escrow: add quote + mock card fields, rename default status to unfunded
    op.add_column("escrow", sa.Column("quoted_amount", Numeric(12, 2), nullable=False, server_default="0.00"))
    op.add_column("escrow", sa.Column("card_brand", sa.String(), nullable=True))
    op.add_column("escrow", sa.Column("card_last4", sa.String(), nullable=True))
    op.alter_column("escrow", "status", server_default="unfunded",
                    existing_type=sa.String(), nullable=False)
    op.execute("UPDATE escrow SET status = 'unfunded' WHERE status = 'held' AND funded_at IS NULL")

    # Job: lifecycle timestamps
    op.add_column("job", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("job", sa.Column("completed_at", sa.DateTime(), nullable=True))

    # New tables
    op.create_table(
        "jobaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contractorwallet",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contractor_id", sa.Integer(), nullable=False),
        sa.Column("pending_balance", Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("available_balance", Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contractor_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contractor_id"),
    )
    op.create_table(
        "wallettransaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contractor_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("amount", Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["contractor_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("wallettransaction")
    op.drop_table("contractorwallet")
    op.drop_table("jobaction")
    op.drop_column("job", "completed_at")
    op.drop_column("job", "started_at")
    op.alter_column("escrow", "status", server_default="held",
                    existing_type=sa.String(), nullable=False)
    op.drop_column("escrow", "card_last4")
    op.drop_column("escrow", "card_brand")
    op.drop_column("escrow", "quoted_amount")
