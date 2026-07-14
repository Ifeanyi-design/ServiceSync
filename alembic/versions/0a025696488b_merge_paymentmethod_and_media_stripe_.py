"""merge paymentmethod and media/stripe heads

Revision ID: 0a025696488b
Revises: 2fcb8206e813, k5l6m7n8o9p0
Create Date: 2026-07-14 16:13:41.211421

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a025696488b'
down_revision: Union[str, Sequence[str], None] = ('2fcb8206e813', 'k5l6m7n8o9p0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
