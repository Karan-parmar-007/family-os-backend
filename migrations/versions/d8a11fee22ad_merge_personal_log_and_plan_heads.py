"""merge personal log and plan heads

Revision ID: d8a11fee22ad
Revises: f2v12personallognofamily, f2v19currency
Create Date: 2026-07-09 16:34:55.773307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a11fee22ad'
down_revision: Union[str, Sequence[str], None] = ('f2v12personallognofamily', 'f2v19currency')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
