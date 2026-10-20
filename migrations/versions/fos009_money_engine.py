"""Money engine: idempotent recurring runs, run tracking, list indexes.

- fos_money_events.period_key + unique (rule_id, period_key): a rule can post
  at most once per scheduled period, even if two workers race.
- fos_money_rules gains anchor_day (month-end safe stepping), run tracking and
  optional end conditions (end_at / max_runs).
- Partial index on due ACTIVE rules; composite list indexes for events.

Revision ID: fos009_money_engine
Revises: fos008_categories
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fos009_money_engine"
down_revision: Union[str, None] = "fos008_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fos_money_rules", sa.Column("anchor_day", sa.SmallInteger(), nullable=True))
    op.add_column("fos_money_rules", sa.Column("every_n", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("fos_money_rules", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fos_money_rules", sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("fos_money_rules", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fos_money_rules", sa.Column("max_runs", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE fos_money_rules SET anchor_day = EXTRACT(DAY FROM next_run_at)::smallint"
    )
    op.execute(
        """
        UPDATE fos_money_rules r SET run_count = s.n, last_run_at = s.last
        FROM (
          SELECT rule_id, count(*) AS n, max(occurred_at) AS last
          FROM fos_money_events WHERE rule_id IS NOT NULL GROUP BY rule_id
        ) s
        WHERE s.rule_id = r.id
        """
    )

    op.add_column("fos_money_events", sa.Column("period_key", sa.Date(), nullable=True))
    op.add_column(
        "fos_money_events",
        sa.Column("is_overdrawn", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "fos_money_events",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute(
        """
        UPDATE fos_money_events SET owner_user_id = created_by
        WHERE scope = 'PERSONAL' AND owner_user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE fos_money_rules SET owner_user_id = created_by
        WHERE scope = 'PERSONAL' AND owner_user_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fos_money_events_rule_period
        ON fos_money_events (rule_id, period_key)
        WHERE rule_id IS NOT NULL AND period_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_money_rules_due
        ON fos_money_rules (next_run_at) WHERE status = 'ACTIVE'
        """
    )
    op.create_index("ix_fos_money_rules_family_kind", "fos_money_rules", ["family_id", "kind", "status"])
    op.create_index("ix_fos_money_rules_owner_kind", "fos_money_rules", ["owner_user_id", "kind", "status"])
    op.drop_index("ix_fos_money_rules_family_id", table_name="fos_money_rules", if_exists=True)
    op.drop_index("ix_fos_money_rules_owner_user_id", table_name="fos_money_rules", if_exists=True)
    op.create_index("ix_fos_money_rules_insurance_id", "fos_money_rules", ["insurance_id"])
    op.create_index("ix_fos_money_rules_debt_id", "fos_money_rules", ["debt_id"])

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_money_events_family_kind_time
        ON fos_money_events (family_id, kind, occurred_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_money_events_owner_kind_time
        ON fos_money_events (owner_user_id, kind, occurred_at DESC, id DESC)
        """
    )
    op.drop_index("ix_fos_money_events_family_id", table_name="fos_money_events", if_exists=True)
    op.drop_index("ix_fos_money_events_owner_user_id", table_name="fos_money_events", if_exists=True)

    op.create_index(
        "ix_savings_ledger_source", "savings_ledger", ["source_type", "source_id"]
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_savings_ledger_family_time
        ON savings_ledger (family_id, occurred_at DESC) WHERE pool_type = 'FAMILY'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_savings_ledger_user_time
        ON savings_ledger (user_id, occurred_at DESC) WHERE pool_type = 'PERSONAL'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_savings_ledger_user_time")
    op.execute("DROP INDEX IF EXISTS ix_savings_ledger_family_time")
    op.drop_index("ix_savings_ledger_source", table_name="savings_ledger")
    op.create_index("ix_fos_money_events_owner_user_id", "fos_money_events", ["owner_user_id"])
    op.create_index("ix_fos_money_events_family_id", "fos_money_events", ["family_id"])
    op.execute("DROP INDEX IF EXISTS ix_fos_money_events_owner_kind_time")
    op.execute("DROP INDEX IF EXISTS ix_fos_money_events_family_kind_time")
    op.drop_index("ix_fos_money_rules_debt_id", table_name="fos_money_rules")
    op.drop_index("ix_fos_money_rules_insurance_id", table_name="fos_money_rules")
    op.create_index("ix_fos_money_rules_owner_user_id", "fos_money_rules", ["owner_user_id"])
    op.create_index("ix_fos_money_rules_family_id", "fos_money_rules", ["family_id"])
    op.drop_index("ix_fos_money_rules_owner_kind", table_name="fos_money_rules")
    op.drop_index("ix_fos_money_rules_family_kind", table_name="fos_money_rules")
    op.execute("DROP INDEX IF EXISTS ix_fos_money_rules_due")
    op.execute("DROP INDEX IF EXISTS uq_fos_money_events_rule_period")
    for col in ("updated_at", "is_overdrawn", "period_key"):
        op.drop_column("fos_money_events", col)
    for col in ("max_runs", "end_at", "run_count", "last_run_at", "every_n", "anchor_day"):
        op.drop_column("fos_money_rules", col)
