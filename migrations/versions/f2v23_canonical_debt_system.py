"""Canonical debt, scope views, and payment events (Family Loan Management)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v23canonicaldebtsystem"
down_revision: Union[str, Sequence[str], None] = "f2v22recurringexpensecategory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "debts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("primary_family_id", sa.UUID(), nullable=True),
        sa.Column("debt_name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="ACTIVE", nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("remaining_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("total_paid", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("has_interest", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("interest_type", sa.String(), nullable=True),
        sa.Column("interest_rate", sa.Float(), nullable=True),
        sa.Column("compounding_frequency", sa.String(), nullable=True),
        sa.Column("fixed_fee_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("interest_increase_every", sa.String(), nullable=True),
        sa.Column("interest_increase_percentage", sa.Float(), nullable=True),
        sa.Column("next_interest_increase_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("has_emi", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("emi_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("emi_every", sa.String(), server_default="MONTHLY", nullable=True),
        sa.Column("tenure_months", sa.Integer(), nullable=True),
        sa.Column("emi_next_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requires_confirmation", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("bounce_fine_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("allow_auto_default", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("legacy_family_debt_id", sa.UUID(), nullable=True),
        sa.Column("legacy_personal_debt_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["primary_family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_debts_owner_user_id", "debts", ["owner_user_id"])
    op.create_index("ix_debts_primary_family_id", "debts", ["primary_family_id"])
    op.create_index("ix_debts_status", "debts", ["status"])

    op.create_table(
        "debt_scope_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("debt_id", sa.UUID(), nullable=False),
        sa.Column("scope_kind", sa.String(), nullable=False),  # PERSONAL | FAMILY
        sa.Column("family_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("display_type", sa.String(), nullable=True),
        sa.Column("display_total_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("display_remaining_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("display_emi_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("display_interest_rate", sa.Float(), nullable=True),
        sa.Column("is_masked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("show_breakdown", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("access_level", sa.String(), server_default="FAMILY", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("debt_id", "scope_kind", "family_id", "user_id", name="uq_debt_scope_views_target"),
    )
    op.create_index("ix_debt_scope_views_debt_id", "debt_scope_views", ["debt_id"])
    op.create_index("ix_debt_scope_views_family_id", "debt_scope_views", ["family_id"])
    op.create_index("ix_debt_scope_views_user_id", "debt_scope_views", ["user_id"])

    op.create_table(
        "debt_payment_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("debt_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),  # EMI | PART_PAYMENT | ADJUSTMENT
        sa.Column("period_key", sa.String(), nullable=True),
        sa.Column("scheduled_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("actual_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("principal_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("interest_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("fee_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), server_default="FINALIZED", nullable=False),
        sa.Column("paid_externally", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("part_payment_mode", sa.String(), nullable=True),
        sa.Column("underpayment_policy", sa.String(), nullable=True),
        sa.Column("overpayment_policy", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_debt_payment_events_debt_id", "debt_payment_events", ["debt_id"])
    op.create_index("ix_debt_payment_events_period_key", "debt_payment_events", ["debt_id", "period_key"])

    op.create_table(
        "debt_payment_allocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_event_id", sa.UUID(), nullable=False),
        sa.Column("pool_type", sa.String(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_event_id"], ["debt_payment_events.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_debt_payment_allocations_event_id", "debt_payment_allocations", ["payment_event_id"])

    # Migrate family debts → canonical + family scope view
    op.execute(
        sa.text(
            """
            INSERT INTO debts (
                id, owner_user_id, primary_family_id, debt_name, type, status,
                total_amount, remaining_amount, total_paid,
                has_interest, interest_type, interest_rate, compounding_frequency, fixed_fee_amount,
                interest_increase_every, interest_increase_percentage, next_interest_increase_date,
                has_emi, emi_amount, emi_every, tenure_months, emi_next_date, requires_confirmation,
                bounce_fine_amount, allow_auto_default,
                start_date, end_date, completed_at, document_id,
                legacy_family_debt_id, created_at, updated_at
            )
            SELECT
                id, debt_in_the_name_of, family_id, debt_name, type, status,
                COALESCE(CASE WHEN is_masked THEN real_total_amount ELSE total_amount END, total_amount),
                COALESCE(CASE WHEN is_masked THEN real_remaining_amount ELSE remaining_amount END, remaining_amount),
                total_paid,
                has_interest, interest_type,
                COALESCE(CASE WHEN is_masked THEN real_interest_rate ELSE interest_rate END, interest_rate),
                compounding_frequency, fixed_fee_amount,
                interest_increase_every, interest_increase_percentage, next_interest_increase_date,
                has_emi,
                COALESCE(CASE WHEN is_masked THEN real_emi_amount ELSE emi_amount END, emi_amount),
                emi_every, tenure_months, emi_next_date, requires_confirmation,
                bounce_fine_amount, allow_auto_default,
                start_date, end_date, completed_at, document_id,
                id, created_at, updated_at
            FROM family_debts
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO debt_scope_views (
                id, debt_id, scope_kind, family_id, user_id, is_primary,
                display_name, display_type, display_total_amount, display_remaining_amount,
                display_emi_amount, display_interest_rate, is_masked, show_breakdown,
                access_level, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), fd.id, 'FAMILY', fd.family_id, NULL, true,
                fd.debt_name, fd.type, fd.total_amount, fd.remaining_amount,
                fd.emi_amount, fd.interest_rate, fd.is_masked, fd.show_split_to_family,
                fd.access_level, fd.created_at, fd.updated_at
            FROM family_debts fd
            """
        )
    )

    # Migrate personal debts → canonical + personal scope view
    # Use new UUIDs for debts that would collide with family debt ids (unlikely but safe)
    op.execute(
        sa.text(
            """
            INSERT INTO debts (
                id, owner_user_id, primary_family_id, debt_name, type, status,
                total_amount, remaining_amount, total_paid,
                has_interest, interest_type, interest_rate, compounding_frequency, fixed_fee_amount,
                interest_increase_every, interest_increase_percentage, next_interest_increase_date,
                has_emi, emi_amount, emi_every, tenure_months, emi_next_date, requires_confirmation,
                bounce_fine_amount, allow_auto_default,
                start_date, end_date, completed_at, document_id,
                legacy_personal_debt_id, created_at, updated_at
            )
            SELECT
                CASE WHEN EXISTS (SELECT 1 FROM debts d WHERE d.id = pd.id)
                     THEN gen_random_uuid() ELSE pd.id END,
                pd.user_id, pd.family_id, pd.debt_name, pd.type, pd.status,
                pd.total_amount, pd.remaining_amount, pd.total_paid,
                pd.has_interest, pd.interest_type, pd.interest_rate, pd.compounding_frequency, pd.fixed_fee_amount,
                pd.interest_increase_every, pd.interest_increase_percentage, pd.next_interest_increase_date,
                pd.has_emi, pd.emi_amount, pd.emi_every, pd.tenure_months, pd.emi_next_date, pd.requires_confirmation,
                pd.bounce_fine_amount, pd.allow_auto_default,
                pd.start_date, pd.end_date, pd.completed_at, pd.document_id,
                pd.id, pd.created_at, pd.updated_at
            FROM personal_debts pd
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO debt_scope_views (
                id, debt_id, scope_kind, family_id, user_id, is_primary,
                display_name, display_type, display_total_amount, display_remaining_amount,
                display_emi_amount, display_interest_rate, is_masked, show_breakdown,
                access_level, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), d.id, 'PERSONAL', NULL, d.owner_user_id, true,
                d.debt_name, d.type, d.total_amount, d.remaining_amount,
                d.emi_amount, d.interest_rate, false, true,
                'PRIVATE', d.created_at, d.updated_at
            FROM debts d
            WHERE d.legacy_personal_debt_id IS NOT NULL
            """
        )
    )

    # Keep scheduled_jobs on FAMILY_DEBT / PERSONAL_DEBT for backward compatibility.
    # Canonical debts share the same UUID as legacy rows when possible.


def downgrade() -> None:
    op.drop_index("ix_debt_payment_allocations_event_id", table_name="debt_payment_allocations")
    op.drop_table("debt_payment_allocations")
    op.drop_index("ix_debt_payment_events_period_key", table_name="debt_payment_events")
    op.drop_index("ix_debt_payment_events_debt_id", table_name="debt_payment_events")
    op.drop_table("debt_payment_events")
    op.drop_index("ix_debt_scope_views_user_id", table_name="debt_scope_views")
    op.drop_index("ix_debt_scope_views_family_id", table_name="debt_scope_views")
    op.drop_index("ix_debt_scope_views_debt_id", table_name="debt_scope_views")
    op.drop_table("debt_scope_views")
    op.drop_index("ix_debts_status", table_name="debts")
    op.drop_index("ix_debts_primary_family_id", table_name="debts")
    op.drop_index("ix_debts_owner_user_id", table_name="debts")
    op.drop_table("debts")
