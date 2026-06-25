"""add escrow and dispute tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create escrow table
    op.create_table(
        "escrow",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("job.id"), unique=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("contractor_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("platform_fee", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("contractor_payout", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("customer_refund", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("status", sa.String(), nullable=False, server_default="held"),
        sa.Column("payment_gateway_id", sa.String(), nullable=True),
        sa.Column("payout_reference_id", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("funded_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create dispute table
    op.create_table(
        "dispute",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("escrow_id", sa.Integer(), sa.ForeignKey("escrow.id"), unique=True, nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("job.id"), nullable=False),
        sa.Column("raised_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_ai"),
        sa.Column("ai_arbitration_summary", sa.String(), nullable=True),
        sa.Column("ai_recommended_refund_pct", sa.Float(), nullable=True),
        sa.Column("resolution_notes", sa.String(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("dispute")
    op.drop_table("escrow")
