"""Plan 07 – Goals simplify: drop schedule columns, add notes + completed_at.

Revision ID: f2v16goalssimplify
Revises: f2v15savingsplansv2
Create Date: 2026-07-08 00:02:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f2v16goalssimplify"
down_revision: Union[str, Sequence[str], None] = "f2v15savingsplansv2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEDULE_COLS = [
    "contribution_amount", "contribution_every", "next_contribution_date",
    "auto_deduct", "funded_from", "target_date",
]


def upgrade() -> None:
    # Cancel pending GOAL_CONTRIB jobs
    op.execute(
        """UPDATE scheduled_jobs SET status = 'CANCELLED'
           WHERE job_type = 'GOAL_CONTRIB'
           AND status IN ('SCHEDULED', 'AWAITING_CONFIRMATION', 'DELAYED')"""
    )

    for table in ["family_goals", "personal_goals"]:
        for col in SCHEDULE_COLS:
            try:
                op.drop_column(table, col)
            except Exception:
                pass  # Column may already not exist
        op.add_column(table, sa.Column("notes", sa.Text(), nullable=True))
        op.add_column(table, sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ))
        op.execute(
            f"UPDATE {table} SET completed_at = updated_at WHERE status = 'ACHIEVED'"
        )


def downgrade() -> None:
    for table in ["family_goals", "personal_goals"]:
        op.drop_column(table, "completed_at")
        op.drop_column(table, "notes")
        for col in SCHEDULE_COLS:
            op.add_column(table, sa.Column(col, sa.String(), nullable=True))
