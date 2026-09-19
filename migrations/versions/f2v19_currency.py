"""Plan 10 – Currency: add user currency fields + currency_rates table.

Revision ID: f2v19currency
Revises: f2v18notificationsmeta
Create Date: 2026-07-08 00:05:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f2v19currency"
down_revision: Union[str, Sequence[str], None] = "f2v18notificationsmeta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. User table: currency preferences + super admin flag
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column(
        "is_super_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False
    ))
    op.add_column("users", sa.Column(
        "preferred_currency", sa.String(length=8), server_default="INR", nullable=False
    ))
    op.add_column("users", sa.Column(
        "personal_currency", sa.String(length=8), server_default="INR", nullable=False
    ))

    # ------------------------------------------------------------------
    # 2. currency_rates table
    # ------------------------------------------------------------------
    op.create_table(
        "currency_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("quote_currency", sa.String(length=8), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", sa.String(), server_default="DRAFT", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_by", sa.UUID(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["finalized_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_currency_rates_pair", "currency_rates", ["base_currency", "quote_currency"])
    op.create_index("ix_currency_rates_status", "currency_rates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_currency_rates_status", "currency_rates")
    op.drop_index("ix_currency_rates_pair", "currency_rates")
    op.drop_table("currency_rates")
    op.drop_column("users", "personal_currency")
    op.drop_column("users", "preferred_currency")
    op.drop_column("users", "is_super_admin")
