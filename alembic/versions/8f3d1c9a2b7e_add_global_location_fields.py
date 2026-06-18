"""Add global location fields
Revision ID: 8f3d1c9a2b7e
Revises: dba0374571a1
Create Date: 2026-06-17 16:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f3d1c9a2b7e'
down_revision: Union[str, Sequence[str], None] = 'dba0374571a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user', sa.Column('country', sa.String(), nullable=True))
    op.add_column('user', sa.Column('state_or_province', sa.String(), nullable=True))
    op.add_column('user', sa.Column('city', sa.String(), nullable=True))
    op.add_column('user', sa.Column('area', sa.String(), nullable=True))
    op.add_column('user', sa.Column('postal_code', sa.String(), nullable=True))
    op.add_column('user', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('user', sa.Column('longitude', sa.Float(), nullable=True))

    op.add_column('job', sa.Column('urgency', sa.String(), nullable=True))
    op.add_column('job', sa.Column('is_emergency', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('job', sa.Column('country', sa.String(), nullable=True))
    op.add_column('job', sa.Column('state_or_province', sa.String(), nullable=True))
    op.add_column('job', sa.Column('city', sa.String(), nullable=True))
    op.add_column('job', sa.Column('area', sa.String(), nullable=True))
    op.add_column('job', sa.Column('postal_code', sa.String(), nullable=True))
    op.add_column('job', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('job', sa.Column('longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('job', 'longitude')
    op.drop_column('job', 'latitude')
    op.drop_column('job', 'postal_code')
    op.drop_column('job', 'area')
    op.drop_column('job', 'city')
    op.drop_column('job', 'state_or_province')
    op.drop_column('job', 'country')
    op.drop_column('job', 'is_emergency')
    op.drop_column('job', 'urgency')

    op.drop_column('user', 'longitude')
    op.drop_column('user', 'latitude')
    op.drop_column('user', 'postal_code')
    op.drop_column('user', 'area')
    op.drop_column('user', 'city')
    op.drop_column('user', 'state_or_province')
    op.drop_column('user', 'country')
