"""Family recurring income flags.

Revision ID: f2v9famrecflags
Revises: f2v8recincomesplits
Create Date: 2026-07-04 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v9famrecflags"
down_revision: Union[str, Sequence[str], None] = "f2v8recincomesplits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recurring_incomes",
        sa.Column("is_family_managed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "recurring_incomes",
        sa.Column("let_everyone_edit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # Heuristic: existing single-family-split incomes were likely family quick-adds.
    op.execute(
        """
        UPDATE recurring_incomes ri
        SET is_family_managed = true
        WHERE (
            SELECT COUNT(*) FROM recurring_income_family_splits s
            WHERE s.income_id = ri.id
        ) = 1
        """
    )


def downgrade() -> None:
    op.drop_column("recurring_incomes", "let_everyone_edit")
    op.drop_column("recurring_incomes", "is_family_managed")
