"""Unify per-family personal savings into a single global personal account.

Revision ID: f2v7unifypersonal
Revises: f2v6nosubfam
Create Date: 2026-07-02 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v7unifypersonal"
down_revision: Union[str, Sequence[str], None] = "f2v6nosubfam"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge legacy GLOBAL_PERSONAL ledger rows into PERSONAL.
    op.execute(
        "UPDATE savings_ledger SET pool_type = 'PERSONAL' WHERE pool_type = 'GLOBAL_PERSONAL'"
    )

    # Roll per-family personal balances into the user-level personal account.
    op.execute(
        """
        INSERT INTO user_global_personal_savings (id, user_id, origin_amount, total_savings, created_at, updated_at)
        SELECT gen_random_uuid(), pts.user_id, 0, SUM(pts.total_savings), NOW(), NOW()
        FROM personal_total_savings pts
        GROUP BY pts.user_id
        ON CONFLICT (user_id) DO UPDATE
        SET total_savings = user_global_personal_savings.total_savings + EXCLUDED.total_savings,
            updated_at = NOW()
        """
    )

    op.drop_table("personal_total_savings")


def downgrade() -> None:
    op.create_table(
        "personal_total_savings",
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("origin_amount", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("total_savings", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("keep_in_family_only", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("family_id", "user_id"),
    )
