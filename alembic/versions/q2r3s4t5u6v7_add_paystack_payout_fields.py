"""add paystack payout fields to user

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q2r3s4t5u6v7"
down_revision: Union[str, Sequence[str], None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("paystack_recipient_code", sa.String(), nullable=True))
    op.add_column("user", sa.Column("payout_bank_name", sa.String(), nullable=True))
    op.add_column("user", sa.Column("payout_bank_code", sa.String(), nullable=True))
    op.add_column("user", sa.Column("payout_account_number", sa.String(), nullable=True))
    op.add_column("user", sa.Column("payout_account_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "payout_account_name")
    op.drop_column("user", "payout_account_number")
    op.drop_column("user", "payout_bank_code")
    op.drop_column("user", "payout_bank_name")
    op.drop_column("user", "paystack_recipient_code")
