"""Categories: drop seeded defaults, per-scope uniqueness, category_id everywhere.

- owner_user_id no longer references legacy users (identity is fos_profiles.id).
- Seeded defaults that nothing uses are deleted; used ones become normal rows.
- Duplicate names (case-insensitive) inside one list are merged.
- Assets, insurance and vault items get a category_id (backfilled by name).

Revision ID: fos008_categories
Revises: fos007_categories
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fos008_categories"
down_revision: Union[str, None] = "fos007_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ID_REFS = (
    ("fos_money_rules", "category_id"),
    ("fos_money_events", "category_id"),
    ("fos_debts", "category_id"),
)

_NEW_REFS = (
    "family_assets",
    "personal_assets",
    "family_insurances",
    "personal_insurances",
    "fos_vault_items",
)


def _fk_names(inspector, table: str) -> set[str]:
    return {fk["name"] for fk in inspector.get_foreign_keys(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "fos_categories_owner_user_id_fkey" in _fk_names(inspector, "fos_categories"):
        op.drop_constraint(
            "fos_categories_owner_user_id_fkey", "fos_categories", type_="foreignkey"
        )

    cols = {c["name"] for c in inspector.get_columns("fos_categories")}
    if "updated_at" not in cols:
        op.add_column(
            "fos_categories",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    for table in _NEW_REFS:
        tcols = {c["name"] for c in inspector.get_columns(table)}
        if "category_id" not in tcols:
            op.add_column(
                table,
                sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
            )
    op.alter_column("fos_vault_items", "category", nullable=True)

    # Personal categories belong to a profile; drop rows whose owner is gone.
    op.execute(
        """
        DELETE FROM fos_categories c
        WHERE c.scope = 'PERSONAL'
          AND NOT EXISTS (SELECT 1 FROM fos_profiles p WHERE p.id = c.owner_user_id)
        """
    )

    # Backfill category_id from the stored names before defaults are pruned.
    op.execute(
        """
        UPDATE family_assets a SET category_id = c.id
        FROM fos_categories c
        WHERE a.category_id IS NULL AND c.scope = 'FAMILY' AND c.category_type = 'ASSET'
          AND c.family_id = a.family_id AND lower(c.name) = lower(a.type)
        """
    )
    op.execute(
        """
        UPDATE personal_assets a SET category_id = c.id
        FROM fos_categories c
        WHERE a.category_id IS NULL AND c.scope = 'PERSONAL' AND c.category_type = 'ASSET'
          AND c.owner_user_id = a.user_id AND lower(c.name) = lower(a.type)
        """
    )
    op.execute(
        """
        UPDATE fos_vault_items v SET category_id = c.id
        FROM fos_categories c
        WHERE v.category_id IS NULL AND v.category IS NOT NULL
          AND c.category_type = CASE WHEN v.kind = 'PASSWORD' THEN 'VAULT_PASSWORD' ELSE 'VAULT_DOCUMENT' END
          AND lower(c.name) = lower(v.category)
          AND (
            (v.scope = 'FAMILY' AND c.scope = 'FAMILY' AND c.family_id = v.family_id)
            OR (v.scope = 'PERSONAL' AND c.scope = 'PERSONAL' AND c.owner_user_id = v.owner_user_id)
          )
        """
    )

    used = " OR ".join(
        [f"EXISTS (SELECT 1 FROM {t} r WHERE r.{col} = c.id)" for t, col in _ID_REFS]
        + [f"EXISTS (SELECT 1 FROM {t} r WHERE r.category_id = c.id)" for t in _NEW_REFS]
    )
    if "is_default" in cols:
        op.execute(f"DELETE FROM fos_categories c WHERE c.is_default AND NOT ({used})")
        op.drop_column("fos_categories", "is_default")

    # Merge case-insensitive duplicates into the oldest row of each list.
    op.execute(
        """
        CREATE TEMP TABLE _cat_dupes ON COMMIT DROP AS
        SELECT id, keep_id FROM (
          SELECT id,
                 first_value(id) OVER w AS keep_id
          FROM fos_categories
          WINDOW w AS (
            PARTITION BY scope,
                         CASE WHEN scope = 'FAMILY' THEN family_id ELSE owner_user_id END,
                         category_type, lower(name)
            ORDER BY created_at, id
          )
        ) s WHERE id <> keep_id
        """
    )
    for table, col in _ID_REFS + tuple((t, "category_id") for t in _NEW_REFS):
        op.execute(
            f"UPDATE {table} r SET {col} = d.keep_id FROM _cat_dupes d WHERE r.{col} = d.id"
        )
    op.execute("DELETE FROM fos_categories c USING _cat_dupes d WHERE c.id = d.id")

    # Dangling ids (rules/events never had an FK) are cleared before adding one.
    for table in ("fos_money_rules", "fos_money_events"):
        op.execute(
            f"""
            UPDATE {table} r SET category_id = NULL
            WHERE r.category_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM fos_categories c WHERE c.id = r.category_id)
            """
        )

    inspector = sa.inspect(bind)
    for table in ("fos_money_rules", "fos_money_events") + _NEW_REFS:
        name = f"{table}_category_id_fkey"
        if name not in _fk_names(inspector, table):
            op.create_foreign_key(
                name, table, "fos_categories", ["category_id"], ["id"], ondelete="SET NULL"
            )
        op.create_index(f"ix_{table}_category_id", table, ["category_id"], if_not_exists=True)
    op.create_index("ix_fos_debts_category_id", "fos_debts", ["category_id"], if_not_exists=True)

    op.drop_index("ix_fos_categories_category_type", table_name="fos_categories", if_exists=True)
    op.drop_index("ix_fos_categories_owner_user_id", table_name="fos_categories", if_exists=True)
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fos_categories_family_name
        ON fos_categories (family_id, category_type, lower(name))
        WHERE scope = 'FAMILY'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fos_categories_personal_name
        ON fos_categories (owner_user_id, category_type, lower(name))
        WHERE scope = 'PERSONAL'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_fos_categories_personal_name")
    op.execute("DROP INDEX IF EXISTS uq_fos_categories_family_name")
    op.create_index("ix_fos_categories_owner_user_id", "fos_categories", ["owner_user_id"])
    op.create_index("ix_fos_categories_category_type", "fos_categories", ["category_type"])
    op.drop_index("ix_fos_debts_category_id", table_name="fos_debts", if_exists=True)
    for table in ("fos_money_rules", "fos_money_events") + _NEW_REFS:
        op.drop_index(f"ix_{table}_category_id", table_name=table, if_exists=True)
        op.drop_constraint(f"{table}_category_id_fkey", table, type_="foreignkey")
    for table in _NEW_REFS:
        op.drop_column(table, "category_id")
    op.execute("UPDATE fos_vault_items SET category = '' WHERE category IS NULL")
    op.alter_column("fos_vault_items", "category", nullable=False)
    op.add_column(
        "fos_categories",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.drop_column("fos_categories", "updated_at")
