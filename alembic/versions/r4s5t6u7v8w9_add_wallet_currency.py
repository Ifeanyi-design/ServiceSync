"""add currency to contractor wallet and wallet transactions

Revision ID: r4s5t6u7v8w9
Revises: q2r3s4t5u6v7
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r4s5t6u7v8w9"
down_revision: Union[str, Sequence[str], None] = "q2r3s4t5u6v7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contractorwallet", sa.Column("currency", sa.String(), nullable=False, server_default="USD"))
    op.add_column("wallettransaction", sa.Column("currency", sa.String(), nullable=False, server_default="USD"))


def downgrade() -> None:
    op.drop_column("wallettransaction", "currency")
    op.drop_column("contractorwallet", "currency")