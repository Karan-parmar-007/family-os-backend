"""Plan 06 – Savings Plans v2: add requires_confirmation, skip_fine_amount, completed_at.

Revision ID: f2v15savingsplansv2
Revises: f2v14insurance
Create Date: 2026-07-08 00:01:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f2v15savingsplansv2"
down_revision: Union[str, Sequence[str], None] = "f2v14insurance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["family_savings_plans", "personal_savings_plans"]


def upgrade() -> None:
    for table in TABLES:
        # requires_confirmation replaces confirm_contributions
        op.add_column(table, sa.Column(
            "requires_confirmation", sa.Boolean(),
            server_default=sa.text("false"), nullable=False
        ))
        op.execute(f"UPDATE {table} SET requires_confirmation = confirm_contributions")

        op.add_column(table, sa.Column(
            "skip_fine_amount", sa.Numeric(12, 2),
            server_default=sa.text("0"), nullable=False
        ))
        op.add_column(table, sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ))
        # Set completed_at for already-completed plans
        op.execute(f"UPDATE {table} SET completed_at = updated_at WHERE status = 'COMPLETED'")


def downgrade() -> None:
    for table in TABLES:
        for col in ["requires_confirmation", "skip_fine_amount", "completed_at"]:
            op.drop_column(table, col)
