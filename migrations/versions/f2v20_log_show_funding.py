"""Add show_funding_to_family to family income/expense logs (Plan 12)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v20logshowfunding"
down_revision: Union[str, Sequence[str], None] = "d563e0b6eaaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "family_income_logs",
        sa.Column(
            "show_funding_to_family",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "family_expense_logs",
        sa.Column(
            "show_funding_to_family",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("family_expense_logs", "show_funding_to_family")
    op.drop_column("family_income_logs", "show_funding_to_family")
