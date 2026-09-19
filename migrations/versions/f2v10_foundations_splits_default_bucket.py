"""Plan 01 – Foundations: payment split tables, default bucket, and ScheduledJob.meta.

Revision ID: f2v10foundations
Revises: f2v9famrecflags
Create Date: 2026-07-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2v10foundations"
down_revision: Union[str, Sequence[str], None] = "f2v9famrecflags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. payment_split_plans
    # ------------------------------------------------------------------
    op.create_table(
        "payment_split_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_split_plans_entity",
        "payment_split_plans",
        ["entity_type", "entity_id"],
    )

    # ------------------------------------------------------------------
    # 2. payment_split_lines
    # ------------------------------------------------------------------
    op.create_table(
        "payment_split_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("pool_type", sa.String(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=True),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["payment_split_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_split_lines_plan_id", "payment_split_lines", ["plan_id"])

    # ------------------------------------------------------------------
    # 3. funding_breakdown_entries
    # ------------------------------------------------------------------
    op.create_table(
        "funding_breakdown_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("pool_type", sa.String(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("direction", sa.String(), nullable=False, server_default="OUT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_funding_breakdown_entity_id", "funding_breakdown_entries", ["entity_id"])
    op.create_index("ix_funding_breakdown_job_id", "funding_breakdown_entries", ["job_id"])

    # ------------------------------------------------------------------
    # 4. default_bucket_entries
    # ------------------------------------------------------------------
    op.create_table(
        "default_bucket_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("period_key", sa.String(), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fine_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settle_ledger_note", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_default_bucket_entity_id", "default_bucket_entries", ["entity_id"]
    )
    op.create_index(
        "ix_default_bucket_family_id", "default_bucket_entries", ["family_id"]
    )
    op.create_index(
        "ix_default_bucket_user_id", "default_bucket_entries", ["user_id"]
    )

    # ------------------------------------------------------------------
    # 5. ScheduledJob.meta — nullable JSONB column
    # ------------------------------------------------------------------
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # 6. Migrate existing open bounced_payments rows to default_bucket_entries
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO default_bucket_entries
            (id, entity_type, entity_id, family_id, user_id, period_key,
             amount, fine_amount, reason, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            bp.debt_scope,       -- e.g. 'FAMILY_DEBT' or 'PERSONAL_DEBT'
            bp.debt_id,
            bp.family_id,
            bp.user_id,
            bp.period_key,
            bp.amount,
            0,                   -- no fine stored in old table
            'BOUNCED',
            CASE bp.status
                WHEN 'BOUNCED'    THEN 'OPEN'
                WHEN 'PAID_LATE'  THEN 'SETTLED'
                WHEN 'WAIVED'     THEN 'WAIVED'
                ELSE 'OPEN'
            END,
            bp.created_at,
            bp.updated_at
        FROM bounced_payments bp
        """
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "meta")

    op.drop_index("ix_default_bucket_user_id", table_name="default_bucket_entries")
    op.drop_index("ix_default_bucket_family_id", table_name="default_bucket_entries")
    op.drop_index("ix_default_bucket_entity_id", table_name="default_bucket_entries")
    op.drop_table("default_bucket_entries")

    op.drop_index("ix_funding_breakdown_job_id", table_name="funding_breakdown_entries")
    op.drop_index("ix_funding_breakdown_entity_id", table_name="funding_breakdown_entries")
    op.drop_table("funding_breakdown_entries")

    op.drop_index("ix_payment_split_lines_plan_id", table_name="payment_split_lines")
    op.drop_table("payment_split_lines")

    op.drop_index("ix_payment_split_plans_entity", table_name="payment_split_plans")
    op.drop_table("payment_split_plans")
