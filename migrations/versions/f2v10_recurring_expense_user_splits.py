"""User-owned recurring expense with per-family splits.

Revision ID: f2v10recexpensesplits
Revises: f2v9famrecflags
Create Date: 2026-07-04 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v10recexpensesplits"
down_revision: Union[str, Sequence[str], None] = "f2v9famrecflags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expense_name", sa.String(length=255), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("personal_savings_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("paid_every", sa.String(), nullable=True),
        sa.Column("repeat_interval_days", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_months", sa.Integer(), nullable=True),
        sa.Column("repeat_interval_years", sa.Integer(), nullable=True),
        sa.Column("next_payment_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("show_docs_to_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("repeat_doc_with_logs", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_family_managed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("let_everyone_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_expenses_user_id", "recurring_expenses", ["user_id"])

    op.create_table(
        "recurring_expense_family_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("split_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["expense_id"], ["recurring_expenses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "expense_id", "family_id", name="uq_recurring_expense_family_splits_expense_family"
        ),
    )
    op.create_index(
        "ix_recurring_expense_family_splits_expense_id",
        "recurring_expense_family_splits",
        ["expense_id"],
    )
    op.create_index(
        "ix_recurring_expense_family_splits_family_id",
        "recurring_expense_family_splits",
        ["family_id"],
    )

    op.create_table(
        "recurring_expense_doc_access",
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["expense_id"], ["recurring_expenses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("expense_id", "user_id"),
    )

    op.add_column(
        "family_expense_logs",
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("family_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("personal_savings_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("personal_savings_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("recurring_expense_family_split_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("added_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("show_doc_to_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_foreign_key(
        "fk_family_expense_logs_personal_savings_user_id",
        "family_expense_logs",
        "users",
        ["personal_savings_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_family_expense_logs_added_by_user_id",
        "family_expense_logs",
        "users",
        ["added_by_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_family_expense_logs_recurring_expense_family_split_id",
        "family_expense_logs",
        "recurring_expense_family_splits",
        ["recurring_expense_family_split_id"],
        ["id"],
    )

    op.add_column(
        "personal_expense_logs",
        sa.Column("family_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "personal_expense_logs",
        sa.Column("family_expense_log_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "personal_expense_logs",
        sa.Column("show_doc_to_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_foreign_key(
        "fk_personal_expense_logs_family_expense_log_id",
        "personal_expense_logs",
        "family_expense_logs",
        ["family_expense_log_id"],
        ["id"],
    )

    op.create_table(
        "family_expense_log_doc_access_v2",
        sa.Column("log_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["log_id"], ["family_expense_logs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("log_id", "user_id"),
    )

    # Backfill total_amount from legacy amount column
    op.execute(
        """
        UPDATE family_expense_logs
        SET total_amount = amount,
            family_amount = amount,
            added_by_user_id = logged_by
        WHERE total_amount IS NULL
        """
    )


def downgrade() -> None:
    op.drop_table("family_expense_log_doc_access_v2")
    op.drop_constraint(
        "fk_personal_expense_logs_family_expense_log_id", "personal_expense_logs", type_="foreignkey"
    )
    op.drop_column("personal_expense_logs", "show_doc_to_all")
    op.drop_column("personal_expense_logs", "family_expense_log_id")
    op.drop_column("personal_expense_logs", "family_amount")

    op.drop_constraint(
        "fk_family_expense_logs_recurring_expense_family_split_id",
        "family_expense_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_family_expense_logs_added_by_user_id", "family_expense_logs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_family_expense_logs_personal_savings_user_id", "family_expense_logs", type_="foreignkey"
    )
    op.drop_column("family_expense_logs", "show_doc_to_all")
    op.drop_column("family_expense_logs", "added_by_user_id")
    op.drop_column("family_expense_logs", "recurring_expense_family_split_id")
    op.drop_column("family_expense_logs", "personal_savings_user_id")
    op.drop_column("family_expense_logs", "personal_savings_amount")
    op.drop_column("family_expense_logs", "family_amount")
    op.drop_column("family_expense_logs", "total_amount")

    op.drop_table("recurring_expense_doc_access")
    op.drop_table("recurring_expense_family_splits")
    op.drop_table("recurring_expenses")
