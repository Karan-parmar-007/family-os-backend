"""Remove sub-family backend schema.

Revision ID: f2v6nosubfam
Revises: f2v5joincode
Create Date: 2026-07-02 14:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v6nosubfam"
down_revision: Union[str, Sequence[str], None] = "f2v5joincode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES_TO_DROP = [
    "entity_subfamily_shares",
    "personal_savings_subfamily_share",
    "sub_family_invites",
    "sub_family_members",
    "sub_family_total_savings",
    "sub_families",
]

COLUMNS_TO_DROP = {
    "family_assets": ["sub_family_id"],
    "personal_assets": ["sub_family_id"],
    "family_insurances": ["sub_family_id"],
    "personal_insurances": ["sub_family_id"],
    "family_savings_plans": ["sub_family_id"],
    "family_savings_plan_contributions": ["sub_family_id"],
    "personal_savings_plans": ["sub_family_id"],
    "personal_savings_plan_contributions": ["sub_family_id"],
    "family_recurring_incomes": ["sub_family_id"],
    "family_income_logs": ["sub_family_id"],
    "personal_recurring_incomes": ["sub_family_id"],
    "personal_income_logs": ["sub_family_id"],
    "family_goals": ["sub_family_id"],
    "family_goal_contributions": ["sub_family_id"],
    "personal_goals": ["sub_family_id"],
    "personal_goal_contributions": ["sub_family_id"],
    "family_debts": ["sub_family_id"],
    "personal_debts": ["sub_family_id"],
    "personal_savings_logs": ["sub_family_id"],
    "family_expenses": ["sub_family_id"],
    "family_expense_logs": ["sub_family_id"],
    "personal_expenses": ["sub_family_id"],
    "personal_expense_logs": ["sub_family_id"],
    "savings_ledger": ["sub_family_id"],
    "transfers": ["from_sub_family_id", "to_sub_family_id"],
    "scheduled_jobs": ["sub_family_id"],
    "notifications": ["sub_family_id"],
    "bounced_payments": ["sub_family_id"],
}


def upgrade() -> None:
    bind = op.get_bind()

    for table_name, columns in COLUMNS_TO_DROP.items():
        for column_name in columns:
            bind.execute(
                sa.text(
                    f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "{column_name}" CASCADE'
                )
            )

    for table_name in TABLES_TO_DROP:
        bind.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade is not supported for f2v6nosubfam because sub-family data is removed destructively."
    )
