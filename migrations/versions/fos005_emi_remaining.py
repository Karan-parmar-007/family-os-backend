"""Add emi_remaining on fos_money_rules

Revision ID: fos005_emi_remaining
Revises: fos004_money_and_vault
Create Date: 2026-09-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "fos005_emi_remaining"
down_revision: Union[str, None] = "fos004_money_and_vault"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fos_money_rules", sa.Column("emi_remaining", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fos_money_rules", "emi_remaining")
