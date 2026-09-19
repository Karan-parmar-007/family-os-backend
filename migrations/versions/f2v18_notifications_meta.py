"""Plan 09 – Notifications meta column.

Revision ID: f2v18notificationsmeta
Revises: f2v17transfersv2
Create Date: 2026-07-08 00:04:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f2v18notificationsmeta"
down_revision: Union[str, Sequence[str], None] = "f2v17transfersv2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add meta JSONB to notifications for frontend snapshot
    # (related_entity_type / related_entity_id already exist as of f2v2_phase2)
    op.add_column(
        "notifications",
        sa.Column("meta", JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "meta")
