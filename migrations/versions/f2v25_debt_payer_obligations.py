"""Debt balance_for_part_payment + per-payer expected/obligation on split lines."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v25debtpayerobligations"
down_revision: Union[str, Sequence[str], None] = "c34524a8d626"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    debt_cols = {c["name"] for c in inspector.get_columns("debts")}
    if "balance_for_part_payment" not in debt_cols:
        op.add_column(
            "debts",
            sa.Column(
                "balance_for_part_payment",
                sa.Numeric(precision=12, scale=2),
                server_default="0",
                nullable=False,
            ),
        )

    line_cols = {c["name"] for c in inspector.get_columns("payment_split_lines")}
    if "expected_total" not in line_cols:
        op.add_column(
            "payment_split_lines",
            sa.Column("expected_total", sa.Numeric(precision=12, scale=2), nullable=True),
        )
    if "obligation_remaining" not in line_cols:
        op.add_column(
            "payment_split_lines",
            sa.Column(
                "obligation_remaining",
                sa.Numeric(precision=12, scale=2),
                nullable=True,
            ),
        )

    # Backfill: distribute each debt's remaining_amount across split lines by EMI share.
    op.execute(
        sa.text(
            """
            WITH plans AS (
              SELECT p.id AS plan_id, p.entity_id AS debt_id, d.remaining_amount
              FROM payment_split_plans p
              JOIN debts d ON d.id = p.entity_id
              WHERE p.entity_type IN ('DEBT', 'FAMILY_DEBT', 'PERSONAL_DEBT')
            ),
            line_sums AS (
              SELECT l.plan_id, SUM(l.amount) AS total_emi
              FROM payment_split_lines l
              GROUP BY l.plan_id
            )
            UPDATE payment_split_lines l
            SET
              expected_total = CASE
                WHEN ls.total_emi > 0 THEN ROUND(plans.remaining_amount * (l.amount / ls.total_emi), 2)
                ELSE plans.remaining_amount
              END,
              obligation_remaining = CASE
                WHEN ls.total_emi > 0 THEN ROUND(plans.remaining_amount * (l.amount / ls.total_emi), 2)
                ELSE plans.remaining_amount
              END
            FROM plans
            JOIN line_sums ls ON ls.plan_id = plans.plan_id
            WHERE l.plan_id = plans.plan_id
              AND (l.expected_total IS NULL OR l.obligation_remaining IS NULL)
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    line_cols = {c["name"] for c in inspector.get_columns("payment_split_lines")}
    if "obligation_remaining" in line_cols:
        op.drop_column("payment_split_lines", "obligation_remaining")
    if "expected_total" in line_cols:
        op.drop_column("payment_split_lines", "expected_total")

    debt_cols = {c["name"] for c in inspector.get_columns("debts")}
    if "balance_for_part_payment" in debt_cols:
        op.drop_column("debts", "balance_for_part_payment")
