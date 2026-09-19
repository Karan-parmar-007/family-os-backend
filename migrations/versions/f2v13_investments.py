"""Plan 04 – Investment tables (new module).

Revision ID: f2v13investments
Revises: f2v12assets_simplify
Create Date: 2026-07-07 00:03:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v13investments"
down_revision: Union[str, Sequence[str], None] = "f2v12assets_simplify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # family_investments
    # ------------------------------------------------------------------
    op.create_table(
        "family_investments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(), server_default="FAMILY", nullable=False),
        sa.Column("investment_name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="ACTIVE", nullable=False),
        sa.Column("in_someone_name", sa.UUID(), nullable=True),
        sa.Column("invested_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("current_value", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("return_type", sa.String(), nullable=True),
        sa.Column("annual_return_rate", sa.Float(), nullable=True),
        sa.Column("compounding_frequency", sa.String(), nullable=True),
        sa.Column("has_recurring", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("contribution_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("contribution_every", sa.String(), nullable=True),
        sa.Column("next_contribution_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenure_months", sa.Integer(), nullable=True),
        sa.Column("requires_confirmation", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("maturity_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maturity_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("auto_credit_on_maturity", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("access_level", sa.String(), server_default="FAMILY", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["in_someone_name"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_investments_family_id", "family_investments", ["family_id"])

    op.create_table(
        "family_investment_access",
        sa.Column("investment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("access_level", sa.String(), server_default="READ", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["investment_id"], ["family_investments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("investment_id", "user_id"),
    )

    op.create_table(
        "exclude_from_family_investments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("investment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["investment_id"], ["family_investments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # personal_investments
    # ------------------------------------------------------------------
    op.create_table(
        "personal_investments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(), server_default="PERSONAL", nullable=False),
        sa.Column("investment_name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="ACTIVE", nullable=False),
        sa.Column("invested_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("current_value", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("return_type", sa.String(), nullable=True),
        sa.Column("annual_return_rate", sa.Float(), nullable=True),
        sa.Column("compounding_frequency", sa.String(), nullable=True),
        sa.Column("has_recurring", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("contribution_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("contribution_every", sa.String(), nullable=True),
        sa.Column("next_contribution_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenure_months", sa.Integer(), nullable=True),
        sa.Column("requires_confirmation", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("maturity_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maturity_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("auto_credit_on_maturity", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("access_level", sa.String(), server_default="PRIVATE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_investments_family_id", "personal_investments", ["family_id"])
    op.create_index("ix_personal_investments_user_id", "personal_investments", ["user_id"])

    op.create_table(
        "personal_investment_access",
        sa.Column("investment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("access_level", sa.String(), server_default="READ", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["investment_id"], ["personal_investments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("investment_id", "user_id"),
    )

    # ------------------------------------------------------------------
    # investment_txns (shared table)
    # ------------------------------------------------------------------
    op.create_table(
        "investment_txns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("investment_scope", sa.String(), nullable=False),  # FAMILY | PERSONAL
        sa.Column("investment_id", sa.UUID(), nullable=False),
        sa.Column("txn_type", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("direction", sa.String(), server_default="IN", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(), server_default="MANUAL", nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investment_txns_investment_id", "investment_txns", ["investment_id"])
    op.create_index("ix_investment_txns_investment_scope", "investment_txns", ["investment_scope", "investment_id"])


def downgrade() -> None:
    op.drop_index("ix_investment_txns_investment_scope", "investment_txns")
    op.drop_index("ix_investment_txns_investment_id", "investment_txns")
    op.drop_table("investment_txns")

    op.drop_table("personal_investment_access")
    op.drop_index("ix_personal_investments_user_id", "personal_investments")
    op.drop_index("ix_personal_investments_family_id", "personal_investments")
    op.drop_table("personal_investments")

    op.drop_table("exclude_from_family_investments")
    op.drop_table("family_investment_access")
    op.drop_index("ix_family_investments_family_id", "family_investments")
    op.drop_table("family_investments")
