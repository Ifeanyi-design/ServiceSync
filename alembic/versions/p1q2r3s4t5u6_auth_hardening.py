"""Add auth hardening columns + revoked-token table

Revision ID: p1q2r3s4t5u6
Revises: o9p0q1r2s3t4
Create Date: 2026-07-18 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, Sequence[str], None] = 'o9p0q1r2s3t4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('user', sa.Column('email_verify_token', sa.String(), nullable=True))
    op.add_column('user', sa.Column('email_verify_expiry', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('reset_token', sa.String(), nullable=True))
    op.add_column('user', sa.Column('reset_token_expiry', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('twofa_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('user', sa.Column('twofa_code', sa.String(), nullable=True))
    op.add_column('user', sa.Column('twofa_expiry', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('wa_id', sa.String(), nullable=True))
    op.create_index('ix_user_wa_id', 'user', ['wa_id'], unique=False)

    op.create_table(
        'revokedtoken',
        sa.Column('jti', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('jti'),
    )


def downgrade() -> None:
    op.drop_table('revokedtoken')
    op.drop_index('ix_user_wa_id', table_name='user')
    op.drop_column('user', 'wa_id')
    op.drop_column('user', 'twofa_expiry')
    op.drop_column('user', 'twofa_code')
    op.drop_column('user', 'twofa_enabled')
    op.drop_column('user', 'reset_token_expiry')
    op.drop_column('user', 'reset_token')
    op.drop_column('user', 'email_verify_expiry')
    op.drop_column('user', 'email_verify_token')
    op.drop_column('user', 'email_verified')
