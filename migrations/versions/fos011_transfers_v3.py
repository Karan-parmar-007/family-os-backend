"""Transfers: direct vs code, idempotency, recurring children, list indexes.

- via_code: destination was resolved from a code (needs receiver acceptance);
  direct transfers (connected family / own family / friend) complete instantly.
- idempotency_key: unique per creator, so a double-submitted form posts once.
- parent_id links a recurring schedule to each run it produced.

Revision ID: fos011_transfers_v3
Revises: fos010_edit_insurance
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fos011_transfers_v3"
down_revision: Union[str, None] = "fos010_edit_insurance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("via_code", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("transfers", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column(
        "transfers",
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transfers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("transfers", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transfers", sa.Column("failure_reason", sa.String(255), nullable=True))
    op.execute("UPDATE transfers SET via_code = requires_confirmation WHERE status = 'PENDING'")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_transfers_idempotency
        ON transfers (created_by, idempotency_key) WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute("CREATE INDEX ix_transfers_family_time ON transfers (family_id, created_at DESC)")
    op.execute("CREATE INDEX ix_transfers_to_family_time ON transfers (to_family_id, created_at DESC)")
    op.execute("CREATE INDEX ix_transfers_from_user_time ON transfers (from_user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_transfers_to_user_time ON transfers (to_user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_transfers_created_by ON transfers (created_by)")
    op.execute(
        """
        CREATE INDEX ix_transfers_recurring_due ON transfers (next_run_date)
        WHERE is_recurring AND status = 'ACTIVE'
        """
    )
    op.execute("CREATE INDEX ix_transfers_parent_id ON transfers (parent_id)")
    op.drop_index("ix_transfers_family_id", table_name="transfers", if_exists=True)
    op.drop_index("ix_transfers_to_family_id", table_name="transfers", if_exists=True)

    op.execute("CREATE INDEX IF NOT EXISTS ix_fos_profiles_created_at ON fos_profiles (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_families_created_at ON families (created_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_time ON notifications (user_id, created_at DESC)"
    )


def downgrade() -> None:
    for name in (
        "ix_notifications_user_time",
        "ix_families_created_at",
        "ix_fos_profiles_created_at",
        "ix_transfers_parent_id",
        "ix_transfers_recurring_due",
        "ix_transfers_created_by",
        "ix_transfers_to_user_time",
        "ix_transfers_from_user_time",
        "ix_transfers_to_family_time",
        "ix_transfers_family_time",
        "uq_transfers_idempotency",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.create_index("ix_transfers_family_id", "transfers", ["family_id"])
    op.create_index("ix_transfers_to_family_id", "transfers", ["to_family_id"])
    for col in ("failure_reason", "completed_at", "parent_id", "idempotency_key", "via_code"):
        op.drop_column("transfers", col)
