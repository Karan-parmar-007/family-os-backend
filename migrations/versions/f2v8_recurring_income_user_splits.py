"""User-owned recurring income with per-family splits.

Revision ID: f2v8recincomesplits
Revises: f2v7unifypersonal
Create Date: 2026-07-02 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v8recincomesplits"
down_revision: Union[str, Sequence[str], None] = "f2v7unifypersonal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop legacy personal recurring income tables (unused in API).
    op.drop_table("personal_recurring_income_access")
    op.drop_table("personal_recurring_incomes")

    # Drop old doc access tied to family_recurring_incomes.
    op.drop_table("family_recurring_income_doc_access")
    op.drop_table("family_recurring_incomes")

    op.create_table(
        "recurring_incomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("income_name", sa.String(length=255), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("personal_savings_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("received_every", sa.String(), nullable=True),
        sa.Column("repeat_interval_days", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_months", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_years", sa.Integer(), nullable=True),
        sa.Column("next_receiving_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("show_docs_to_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("repeat_doc_with_logs", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_incomes_user_id", "recurring_incomes", ["user_id"])

    op.create_table(
        "recurring_income_family_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("split_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["income_id"], ["recurring_incomes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("income_id", "family_id", name="uq_recurring_income_family_splits_income_family"),
    )
    op.create_index(
        "ix_recurring_income_family_splits_income_id",
        "recurring_income_family_splits",
        ["income_id"],
    )
    op.create_index(
        "ix_recurring_income_family_splits_family_id",
        "recurring_income_family_splits",
        ["family_id"],
    )

    op.create_table(
        "recurring_income_doc_access",
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["income_id"], ["recurring_incomes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("income_id", "user_id"),
    )

    op.add_column(
        "family_income_logs",
        sa.Column("recurring_income_family_split_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_family_income_logs_recurring_income_family_split_id",
        "family_income_logs",
        "recurring_income_family_splits",
        ["recurring_income_family_split_id"],
        ["id"],
    )

    op.alter_column("scheduled_jobs", "family_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column(
        "scheduled_jobs",
        sa.Column("awaiting_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "awaiting_since")
    op.alter_column("scheduled_jobs", "family_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_constraint(
        "fk_family_income_logs_recurring_income_family_split_id",
        "family_income_logs",
        type_="foreignkey",
    )
    op.drop_column("family_income_logs", "recurring_income_family_split_id")

    op.drop_table("recurring_income_doc_access")
    op.drop_table("recurring_income_family_splits")
    op.drop_index("ix_recurring_incomes_user_id", table_name="recurring_incomes")
    op.drop_table("recurring_incomes")

    op.create_table(
        "family_recurring_incomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(), server_default="FAMILY", nullable=False),
        sa.Column("income_name", sa.String(length=255), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount_to_be_added_to_family", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_every", sa.String(), nullable=True),
        sa.Column("repeat_interval_days", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_months", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_years", sa.Integer(), nullable=True),
        sa.Column("next_receiving_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("personal_savings_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("personal_savings_user_id", sa.Uuid(), nullable=True),
        sa.Column("earned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("show_docs_to_all", sa.Boolean(), nullable=False),
        sa.Column("repeat_doc_with_logs", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["earned_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["personal_savings_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_recurring_incomes_family_id", "family_recurring_incomes", ["family_id"])

    op.create_table(
        "family_recurring_income_doc_access",
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["income_id"], ["family_recurring_incomes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("income_id", "user_id"),
    )

    op.create_table(
        "personal_recurring_incomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(), server_default="FAMILY", nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("income_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_every", sa.String(), nullable=True),
        sa.Column("next_receiving_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("deducted_from", sa.String(), nullable=True),
        sa.Column("access_level", sa.String(), nullable=False),
        sa.Column("show_docs_to_all", sa.Boolean(), nullable=False),
        sa.Column("repeat_doc_with_logs", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "personal_recurring_income_access",
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_level", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["income_id"], ["personal_recurring_incomes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("income_id", "user_id"),
    )
