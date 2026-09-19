"""Family System V2 phase 4: family relationships and multi-source funding

Revision ID: f2v4relfund
Revises: f2v3recursive
Create Date: 2026-07-01 14:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v4relfund"
down_revision: Union[str, Sequence[str], None] = "f2v3recursive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "family_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_a_id", sa.Uuid(), nullable=False),
        sa.Column("family_b_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("initiated_by_family_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("responded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["family_a_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["family_b_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["initiated_by_family_id"], ["families.id"]),
        sa.ForeignKeyConstraint(["initiated_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["responded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_family_relationships_family_a_id"),
        "family_relationships",
        ["family_a_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_family_relationships_family_b_id"),
        "family_relationships",
        ["family_b_id"],
        unique=False,
    )

    op.add_column("transfers", sa.Column("to_family_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_transfers_to_family_id"), "transfers", ["to_family_id"], unique=False)
    op.create_foreign_key(
        "fk_transfers_to_family_id",
        "transfers",
        "families",
        ["to_family_id"],
        ["id"],
    )

    op.create_table(
        "log_funding_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("pool_type", sa.String(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_log_funding_sources_entity_id"),
        "log_funding_sources",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_log_funding_sources_family_id"),
        "log_funding_sources",
        ["family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_log_funding_sources_family_id"), table_name="log_funding_sources")
    op.drop_index(op.f("ix_log_funding_sources_entity_id"), table_name="log_funding_sources")
    op.drop_table("log_funding_sources")

    op.drop_constraint("fk_transfers_to_family_id", "transfers", type_="foreignkey")
    op.drop_index(op.f("ix_transfers_to_family_id"), table_name="transfers")
    op.drop_column("transfers", "to_family_id")

    op.drop_index(op.f("ix_family_relationships_family_b_id"), table_name="family_relationships")
    op.drop_index(op.f("ix_family_relationships_family_a_id"), table_name="family_relationships")
    op.drop_table("family_relationships")
