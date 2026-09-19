"""Plan 03 – Assets simplify: drop schedule columns, add notes + acquired_on.

Also cancel any pending ASSET_EMI / ASSET_VALUE_INCREASE scheduled jobs.

Revision ID: f2v12assets_simplify
Revises: f2v11debtrework
Create Date: 2026-07-07 00:02:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v12assets_simplify"
down_revision: Union[str, Sequence[str], None] = "f2v11debtrework"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ASSET_SCHEDULE_COLS = [
    "is_increasing",
    "increase_percentage",
    "increase_every",
    "next_increase_date",
    "has_emi",
    "emi_amount",
    "emi_every",
    "emi_next_date",
    "is_per_something",
    "value_per_something",
]

PERSONAL_EXTRA_DROP = ["deducted_from"]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Cancel pending asset jobs
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE scheduled_jobs
        SET status = 'CANCELLED'
        WHERE job_type IN ('ASSET_EMI', 'ASSET_VALUE_INCREASE')
          AND status IN ('SCHEDULED', 'AWAITING_CONFIRMATION', 'DELAYED')
        """
    )

    # ------------------------------------------------------------------
    # 2. family_assets – drop schedule columns, add new ones
    # ------------------------------------------------------------------
    for col in ASSET_SCHEDULE_COLS:
        op.drop_column("family_assets", col)
    op.add_column("family_assets", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("family_assets", sa.Column("acquired_on", sa.Date(), nullable=True))
    # Ensure value is Decimal (it was float); keep as-is, change only type annotation in model
    # Ensure quantity is Decimal (was int)
    op.alter_column("family_assets", "value", type_=sa.Numeric(precision=12, scale=2), existing_type=sa.Float())
    op.alter_column("family_assets", "quantity", type_=sa.Numeric(precision=12, scale=4), existing_type=sa.Integer())

    # ------------------------------------------------------------------
    # 3. personal_assets – same
    # ------------------------------------------------------------------
    for col in ASSET_SCHEDULE_COLS + PERSONAL_EXTRA_DROP:
        op.drop_column("personal_assets", col)
    op.add_column("personal_assets", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("personal_assets", sa.Column("acquired_on", sa.Date(), nullable=True))
    # personal_assets was incorrectly using scope_type FAMILY; fix default to PERSONAL
    op.execute("UPDATE personal_assets SET scope_type = 'PERSONAL'")
    op.alter_column("personal_assets", "value", type_=sa.Numeric(precision=12, scale=2), existing_type=sa.Float())
    op.alter_column("personal_assets", "quantity", type_=sa.Numeric(precision=12, scale=4), existing_type=sa.Integer())


def downgrade() -> None:
    # personal_assets
    op.drop_column("personal_assets", "acquired_on")
    op.drop_column("personal_assets", "notes")
    for col in reversed(PERSONAL_EXTRA_DROP + ASSET_SCHEDULE_COLS):
        # We just add them back as nullable
        op.add_column("personal_assets", sa.Column(col, sa.String(), nullable=True))
    op.alter_column("personal_assets", "value", type_=sa.Float(), existing_type=sa.Numeric(12, 2))
    op.alter_column("personal_assets", "quantity", type_=sa.Integer(), existing_type=sa.Numeric(12, 4))

    # family_assets
    op.drop_column("family_assets", "acquired_on")
    op.drop_column("family_assets", "notes")
    for col in reversed(ASSET_SCHEDULE_COLS):
        op.add_column("family_assets", sa.Column(col, sa.String(), nullable=True))
    op.alter_column("family_assets", "value", type_=sa.Float(), existing_type=sa.Numeric(12, 2))
    op.alter_column("family_assets", "quantity", type_=sa.Integer(), existing_type=sa.Numeric(12, 4))
