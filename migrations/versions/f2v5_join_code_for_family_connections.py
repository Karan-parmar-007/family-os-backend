"""Family System V2 phase 5: family join codes

Adds an 8-digit join_code to each family so families can connect via a simple
code-based flow (no parent/child semantics).

Revision ID: f2v5joincode
Revises: f2v4relfund
Create Date: 2026-07-02 12:50:00.000000
"""

from typing import Sequence, Union

import secrets
import sqlalchemy as sa
from alembic import op

revision: str = "f2v5joincode"
down_revision: Union[str, Sequence[str], None] = "f2v4relfund"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("families", sa.Column("join_code", sa.String(length=8), nullable=True))

    bind = op.get_bind()
    families_missing = list(
        bind.execute(sa.text("SELECT id FROM families WHERE join_code IS NULL")).fetchall()
    )

    for (family_id,) in families_missing:
        # Guarantee uniqueness within the migration.
        while True:
            candidate = f"{secrets.randbelow(100000000):08d}"
            exists = bind.execute(
                sa.text("SELECT 1 FROM families WHERE join_code = :code LIMIT 1"),
                {"code": candidate},
            ).first()
            if exists is None:
                break
        bind.execute(
            sa.text("UPDATE families SET join_code = :code WHERE id = :id"),
            {"code": candidate, "id": str(family_id)},
        )

    op.alter_column("families", "join_code", nullable=False)

    op.create_index(
        op.f("ix_families_join_code"),
        "families",
        ["join_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_families_join_code"), table_name="families")
    op.drop_column("families", "join_code")

