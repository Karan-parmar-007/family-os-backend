"""Family System V2 phase 3: recursive sub-families, EMI/sinking-fund, private global entries

Revision ID: f2v3recursive
Revises: f2v2phase2
Create Date: 2026-07-01 08:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v3recursive"
down_revision: Union[str, Sequence[str], None] = "f2v2phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Recursive sub-family tree ---
    op.add_column(
        "sub_families",
        sa.Column("parent_sub_family_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "sub_families",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        op.f("ix_sub_families_parent_sub_family_id"),
        "sub_families",
        ["parent_sub_family_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_sub_families_parent_sub_family_id",
        "sub_families",
        "sub_families",
        ["parent_sub_family_id"],
        ["id"],
    )

    # --- Savings-plan sinking-fund / EMI config ---
    for table in ("family_savings_plans", "personal_savings_plans"):
        op.add_column(
            table,
            sa.Column(
                "confirm_contributions",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "emi_mode",
                sa.String(),
                nullable=False,
                server_default="FIXED",
            ),
        )

    # --- Owner-only private global-personal entries ---
    op.create_table(
        "user_global_personal_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_global_personal_entries_user_id"),
        "user_global_personal_entries",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_global_personal_entries_user_id"),
        table_name="user_global_personal_entries",
    )
    op.drop_table("user_global_personal_entries")

    for table in ("family_savings_plans", "personal_savings_plans"):
        op.drop_column(table, "emi_mode")
        op.drop_column(table, "confirm_contributions")

    op.drop_constraint(
        "fk_sub_families_parent_sub_family_id",
        "sub_families",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_sub_families_parent_sub_family_id"),
        table_name="sub_families",
    )
    op.drop_column("sub_families", "depth")
    op.drop_column("sub_families", "parent_sub_family_id")
