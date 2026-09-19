"""Add absolute session start for hard 7-day logout.

Revision ID: f2v29sessionstart
Revises: f2v28friendssplits
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v29sessionstart"
down_revision: Union[str, Sequence[str], None] = "f2v28friendssplits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE refresh_tokens SET session_started_at = created_at "
            "WHERE session_started_at IS NULL"
        )
    )
    op.alter_column("refresh_tokens", "session_started_at", nullable=False)


def downgrade() -> None:
    op.drop_column("refresh_tokens", "session_started_at")
