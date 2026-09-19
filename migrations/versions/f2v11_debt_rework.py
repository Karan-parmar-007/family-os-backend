"""Plan 02 – Debt rework: rename columns, add new columns for both debt tables.

Revision ID: f2v11debtrework
Revises: f2v10foundations
Create Date: 2026-07-07 00:01:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v11debtrework"
down_revision: Union[str, Sequence[str], None] = "f2v10foundations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_debt_columns(table: str, is_family: bool) -> None:
    """Add new columns shared by both debt tables."""
    # Rename existing columns (via add + copy + drop)
    # has_installments → has_emi
    op.add_column(table, sa.Column("has_emi", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute(f"UPDATE {table} SET has_emi = has_installments")

    # monthly_emi → emi_amount
    op.add_column(table, sa.Column("emi_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.execute(f"UPDATE {table} SET emi_amount = monthly_emi")

    # installments_every → emi_every
    op.add_column(table, sa.Column("emi_every", sa.String(), nullable=True))
    op.execute(f"UPDATE {table} SET emi_every = installments_every")

    # New columns
    op.add_column(table, sa.Column("total_paid", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False))
    op.execute(f"UPDATE {table} SET total_paid = GREATEST(0, total_amount - remaining_amount)")

    op.add_column(table, sa.Column("compounding_frequency", sa.String(), nullable=True))
    op.add_column(table, sa.Column("fixed_fee_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column(table, sa.Column("tenure_months", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("requires_confirmation", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column(table, sa.Column("bounce_fine_amount", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False))
    op.add_column(table, sa.Column("allow_auto_default", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column(table, sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    if is_family:
        op.add_column(table, sa.Column("is_masked", sa.Boolean(), server_default=sa.text("false"), nullable=False))
        op.add_column(table, sa.Column("real_total_amount", sa.Numeric(precision=12, scale=2), nullable=True))
        op.add_column(table, sa.Column("real_remaining_amount", sa.Numeric(precision=12, scale=2), nullable=True))
        op.add_column(table, sa.Column("real_emi_amount", sa.Numeric(precision=12, scale=2), nullable=True))
        op.add_column(table, sa.Column("real_interest_rate", sa.Float(), nullable=True))
        op.add_column(table, sa.Column("show_split_to_family", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def _drop_debt_columns(table: str, is_family: bool) -> None:
    """Remove new columns (downgrade helper)."""
    cols = [
        "has_emi", "emi_amount", "emi_every", "total_paid",
        "compounding_frequency", "fixed_fee_amount", "tenure_months",
        "requires_confirmation", "bounce_fine_amount", "allow_auto_default",
        "completed_at",
    ]
    if is_family:
        cols += [
            "is_masked", "real_total_amount", "real_remaining_amount",
            "real_emi_amount", "real_interest_rate", "show_split_to_family",
        ]
    for col in cols:
        op.drop_column(table, col)


def upgrade() -> None:
    _add_debt_columns("family_debts", is_family=True)
    _add_debt_columns("personal_debts", is_family=False)


def downgrade() -> None:
    _drop_debt_columns("personal_debts", is_family=False)
    _drop_debt_columns("family_debts", is_family=True)
