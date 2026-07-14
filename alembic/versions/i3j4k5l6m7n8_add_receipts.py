"""add receipts table

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Numeric

revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_number", sa.String(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("escrow_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("contractor_id", sa.Integer(), nullable=False),
        sa.Column("amount", Numeric(12, 2), nullable=False),
        sa.Column("platform_fee", Numeric(12, 2), nullable=False),
        sa.Column("contractor_payout", Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("card_brand", sa.String(), nullable=True),
        sa.Column("card_last4", sa.String(), nullable=True),
        sa.Column("payment_reference", sa.String(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.ForeignKeyConstraint(["escrow_id"], ["escrow.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["contractor_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_receipt_receipt_number", "receipt", ["receipt_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_receipt_receipt_number", table_name="receipt")
    op.drop_table("receipt")
