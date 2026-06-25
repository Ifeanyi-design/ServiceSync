"""Add review table and user verification/reputation fields

Revision ID: a1b2c3d4e5f6
Revises: 8f3d1c9a2b7e
Create Date: 2026-06-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8f3d1c9a2b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add verification and reputation fields to user table
    op.add_column('user', sa.Column('verification_level', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('user', sa.Column('reputation_score', sa.Float(), nullable=True))
    op.add_column('user', sa.Column('availability_status', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # Create review table
    op.create_table('review',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('contractor_id', sa.Integer(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['contractor_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('review')
    op.drop_column('user', 'availability_status')
    op.drop_column('user', 'reputation_score')
    op.drop_column('user', 'verification_level')
