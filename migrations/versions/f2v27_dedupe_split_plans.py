"""Dedupe payment_split_plans and enforce one plan per entity."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2v27dedupesplitplans"
down_revision: Union[str, Sequence[str], None] = "f2v26droplegacydebts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep newest plan per (entity_type, entity_id); drop twin plans from legacy dual-write.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
              SELECT
                id,
                ROW_NUMBER() OVER (
                  PARTITION BY entity_type, entity_id
                  ORDER BY created_at DESC, id DESC
                ) AS rn
              FROM payment_split_plans
            ),
            extras AS (
              SELECT id FROM ranked WHERE rn > 1
            )
            DELETE FROM payment_split_lines
            WHERE plan_id IN (SELECT id FROM extras)
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
              SELECT
                id,
                ROW_NUMBER() OVER (
                  PARTITION BY entity_type, entity_id
                  ORDER BY created_at DESC, id DESC
                ) AS rn
              FROM payment_split_plans
            )
            DELETE FROM payment_split_plans
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes("payment_split_plans")}
    if "ix_payment_split_plans_entity" in existing:
        op.drop_index("ix_payment_split_plans_entity", table_name="payment_split_plans")
    op.create_index(
        "ix_payment_split_plans_entity",
        "payment_split_plans",
        ["entity_type", "entity_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_payment_split_plans_entity", table_name="payment_split_plans")
    op.create_index(
        "ix_payment_split_plans_entity",
        "payment_split_plans",
        ["entity_type", "entity_id"],
        unique=False,
    )
