"""Add let_everyone_edit to family income and expense logs.

Revision ID: f2v11logeveryoneedit
Revises: f2v10recexpensesplits
Create Date: 2026-07-04 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v11logeveryoneedit"
down_revision: Union[str, Sequence[str], None] = "f2v10recexpensesplits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "family_income_logs",
        sa.Column("let_everyone_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column("let_everyone_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("family_expense_logs", "let_everyone_edit")
    op.drop_column("family_income_logs", "let_everyone_edit")
