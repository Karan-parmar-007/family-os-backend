"""transfers next_run_date and end_date timezone aware

Revision ID: d563e0b6eaaa
Revises: d8a11fee22ad
Create Date: 2026-07-09 16:37:15.770224

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd563e0b6eaaa'
down_revision: Union[str, Sequence[str], None] = 'd8a11fee22ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "transfers",
        "next_run_date",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
    )
    op.alter_column(
        "transfers",
        "end_date",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "transfers",
        "next_run_date",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
    )
    op.alter_column(
        "transfers",
        "end_date",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
    )
