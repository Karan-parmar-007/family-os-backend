"""Edit access + insurance installment schedules.

- let_everyone_edit / created_by on family assets, family insurance, vault.
  When off, only the creator and family heads can edit.
- Insurance schedule: INTERVAL (yearly premium split per period from the next
  deduction date) or CUSTOM (explicit dated installments). Installments live in
  fos_insurance_installments and are charged by the scheduler.

Revision ID: fos010_edit_insurance
Revises: fos009_money_engine
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fos010_edit_insurance"
down_revision: Union[str, None] = "fos009_money_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FALSE = sa.text("false")


def upgrade() -> None:
    for table in ("family_assets", "family_insurances", "fos_vault_items"):
        op.add_column(
            table,
            sa.Column("let_everyone_edit", sa.Boolean(), nullable=False, server_default=_FALSE),
        )
    for table in ("family_assets", "family_insurances"):
        op.add_column(table, sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index(f"ix_{table}_created_by", table, ["created_by"])

    for table in ("family_insurances", "personal_insurances"):
        op.add_column(
            table,
            sa.Column("schedule_mode", sa.String(16), nullable=False, server_default="NONE"),
        )
        op.add_column(table, sa.Column("annual_premium", sa.Numeric(12, 2), nullable=True))
        op.execute(
            f"""
            UPDATE {table} i SET schedule_mode = 'LEGACY'
            WHERE EXISTS (
              SELECT 1 FROM fos_money_rules r
              WHERE r.insurance_id = i.id AND r.status = 'ACTIVE'
            )
            """
        )
    op.create_index("ix_personal_insurances_user_id", "personal_insurances", ["user_id"])

    op.create_table(
        "fos_insurance_installments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("insurance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column(
            "paid_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fos_money_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_fos_insurance_installments_amount"),
        sa.UniqueConstraint("insurance_id", "due_at", name="uq_fos_insurance_installments_due"),
    )
    op.execute(
        """
        CREATE INDEX ix_fos_insurance_installments_pending
        ON fos_insurance_installments (due_at) WHERE status = 'PENDING'
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_vault_items_family_kind_time
        ON fos_vault_items (family_id, kind, created_at DESC) WHERE scope = 'FAMILY'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_vault_items_owner_kind_time
        ON fos_vault_items (owner_user_id, kind, created_at DESC) WHERE scope = 'PERSONAL'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_debts_family_time
        ON fos_debts (family_id, created_at DESC) WHERE scope = 'FAMILY'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fos_debts_owner_time
        ON fos_debts (owner_user_id, created_at DESC) WHERE scope = 'PERSONAL'
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_family_assets_family_time ON family_assets (family_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_personal_assets_user_time ON personal_assets (user_id, created_at DESC)"
    )


def downgrade() -> None:
    for name in (
        "ix_personal_assets_user_time",
        "ix_family_assets_family_time",
        "ix_fos_debts_owner_time",
        "ix_fos_debts_family_time",
        "ix_fos_vault_items_owner_kind_time",
        "ix_fos_vault_items_family_kind_time",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.drop_table("fos_insurance_installments")
    op.drop_index("ix_personal_insurances_user_id", table_name="personal_insurances")
    for table in ("family_insurances", "personal_insurances"):
        op.drop_column(table, "annual_premium")
        op.drop_column(table, "schedule_mode")
    for table in ("family_assets", "family_insurances"):
        op.drop_index(f"ix_{table}_created_by", table_name=table)
        op.drop_column(table, "created_by")
    for table in ("family_assets", "family_insurances", "fos_vault_items"):
        op.drop_column(table, "let_everyone_edit")
