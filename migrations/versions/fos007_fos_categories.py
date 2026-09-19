"""Create fos_categories (never included in earlier revisions).

Revision ID: fos007_categories
Revises: fos006_profile_fks
Create Date: 2026-09-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fos007_categories"
down_revision: Union[str, None] = "fos006_profile_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "fos_categories" not in tables:
        op.create_table(
            "fos_categories",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("category_type", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("color", sa.String(length=32), nullable=True),
            sa.Column("icon", sa.String(length=64), nullable=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["family_id"], ["families.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["owner_user_id"], ["users.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_fos_categories_category_type",
            "fos_categories",
            ["category_type"],
        )
        op.create_index("ix_fos_categories_family_id", "fos_categories", ["family_id"])
        op.create_index(
            "ix_fos_categories_owner_user_id",
            "fos_categories",
            ["owner_user_id"],
        )

    if "fos_debts" in tables:
        debt_cols = {col["name"] for col in inspector.get_columns("fos_debts")}
        if "category_id" not in debt_cols:
            op.add_column(
                "fos_debts",
                sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
        fks = {fk["name"] for fk in inspector.get_foreign_keys("fos_debts")}
        if "fos_debts_category_id_fkey" not in fks:
            op.create_foreign_key(
                "fos_debts_category_id_fkey",
                "fos_debts",
                "fos_categories",
                ["category_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "fos_vault_items" in tables:
        vault_cols = {col["name"] for col in inspector.get_columns("fos_vault_items")}
        if "document_id" not in vault_cols:
            op.add_column(
                "fos_vault_items",
                sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
            op.create_foreign_key(
                "fos_vault_items_document_id_fkey",
                "fos_vault_items",
                "documents",
                ["document_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "personal_assets" in tables:
        personal_cols = {col["name"] for col in inspector.get_columns("personal_assets")}
        if "quantity_label" not in personal_cols:
            op.add_column(
                "personal_assets",
                sa.Column("quantity_label", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "personal_assets" in tables:
        cols = {col["name"] for col in inspector.get_columns("personal_assets")}
        if "quantity_label" in cols:
            op.drop_column("personal_assets", "quantity_label")
    if "fos_vault_items" in tables:
        fks = {fk["name"] for fk in inspector.get_foreign_keys("fos_vault_items")}
        if "fos_vault_items_document_id_fkey" in fks:
            op.drop_constraint(
                "fos_vault_items_document_id_fkey",
                "fos_vault_items",
                type_="foreignkey",
            )
        cols = {col["name"] for col in inspector.get_columns("fos_vault_items")}
        if "document_id" in cols:
            op.drop_column("fos_vault_items", "document_id")
    if "fos_debts" in tables:
        fks = {fk["name"] for fk in inspector.get_foreign_keys("fos_debts")}
        if "fos_debts_category_id_fkey" in fks:
            op.drop_constraint(
                "fos_debts_category_id_fkey", "fos_debts", type_="foreignkey"
            )
    if "fos_categories" in tables:
        op.drop_index("ix_fos_categories_owner_user_id", table_name="fos_categories")
        op.drop_index("ix_fos_categories_family_id", table_name="fos_categories")
        op.drop_index("ix_fos_categories_category_type", table_name="fos_categories")
        op.drop_table("fos_categories")
