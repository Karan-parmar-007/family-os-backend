"""Plan 08 – Transfers v2: add requires_confirmation, end_date, show_breakdown, note.

Revision ID: f2v17transfersv2
Revises: f2v16goalssimplify
Create Date: 2026-07-08 00:03:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f2v17transfersv2"
down_revision: Union[str, Sequence[str], None] = "f2v16goalssimplify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column(
        "requires_confirmation", sa.Boolean(),
        server_default=sa.text("true"), nullable=False
    ))
    op.add_column("transfers", sa.Column(
        "end_date", sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column("transfers", sa.Column(
        "show_breakdown_to_receiver", sa.Boolean(),
        server_default=sa.text("true"), nullable=False
    ))
    op.add_column("transfers", sa.Column(
        "note", sa.Text(), nullable=True
    ))
    # Ensure to_family_id is NOT NULL for new transfers (already nullable for legacy)
    # Migrate: set status to ACTIVE for recurring, COMPLETED for non-recurring PENDING
    op.execute(
        "UPDATE transfers SET status = 'COMPLETED' WHERE is_recurring = false AND status = 'PENDING'"
    )
    op.execute(
        "UPDATE transfers SET status = 'ACTIVE' WHERE is_recurring = true AND status = 'PENDING'"
    )


def downgrade() -> None:
    for col in ["requires_confirmation", "end_date", "show_breakdown_to_receiver", "note"]:
        op.drop_column("transfers", col)
