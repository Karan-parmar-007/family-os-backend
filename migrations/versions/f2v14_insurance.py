"""Plan 05 – Insurance: add requires_confirmation, bounce_fine, completed_at.

Revision ID: f2v14_insurance
Revises: f2v13investments
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "f2v14insurance"
down_revision: Union[str, Sequence[str], None] = "f2v13investments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["family_insurances", "personal_insurances"]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column(
            "requires_confirmation", sa.Boolean(),
            server_default=sa.text("true"), nullable=False
        ))
        op.add_column(table, sa.Column(
            "bounce_fine_amount", sa.Numeric(12, 2),
            server_default=sa.text("0"), nullable=False
        ))
        op.add_column(table, sa.Column(
            "allow_auto_lapse", sa.Boolean(),
            server_default=sa.text("true"), nullable=False
        ))
        op.add_column(table, sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ))
        op.add_column(table, sa.Column(
            "insured_user_id", sa.UUID(), nullable=True
        ))

    # Migrate insured_member → insured_user_id if column exists
    op.execute(
        "UPDATE family_insurances SET insured_user_id = insured_member WHERE insured_member IS NOT NULL"
    )


def downgrade() -> None:
    for table in TABLES:
        for col in ["requires_confirmation", "bounce_fine_amount", "allow_auto_lapse", "completed_at", "insured_user_id"]:
            op.drop_column(table, col)
