"""Make family_id optional on personal income/expense logs.

Revision ID: f2v12personallognofamily
Revises: f2v11logeveryoneedit
Create Date: 2026-07-05 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v12personallognofamily"
down_revision: Union[str, Sequence[str], None] = "f2v11logeveryoneedit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("personal_income_logs", "family_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("personal_expense_logs", "family_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.alter_column("personal_expense_logs", "family_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("personal_income_logs", "family_id", existing_type=sa.Uuid(), nullable=False)
