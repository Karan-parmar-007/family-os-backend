"""Add categories and form options for income and expenses (Plan 13)."""
from typing import Sequence, Union
import uuid
import uuid6
import sqlalchemy as sa
from alembic import op

revision: str = "f2v21categoriesandformoptions"
down_revision: Union[str, Sequence[str], None] = "f2v20logshowfunding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create family_income_categories table
    op.create_table(
        "family_income_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("category_name", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_income_categories_family_id",
        "family_income_categories",
        ["family_id"],
        unique=False,
    )

    # 2. Add columns to income tables
    op.add_column(
        "recurring_incomes",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_recurring_incomes_category_id",
        "recurring_incomes",
        "family_income_categories",
        ["category_id"],
        ["id"],
    )
    op.add_column(
        "recurring_incomes",
        sa.Column("added_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_recurring_incomes_added_by_user_id",
        "recurring_incomes",
        "users",
        ["added_by_user_id"],
        ["id"],
    )

    op.add_column(
        "family_income_logs",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_family_income_logs_category_id",
        "family_income_logs",
        "family_income_categories",
        ["category_id"],
        ["id"],
    )

    op.add_column(
        "personal_income_logs",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_personal_income_logs_category_id",
        "personal_income_logs",
        "family_income_categories",
        ["category_id"],
        ["id"],
    )

    # 3. Add columns to expense tables
    op.add_column(
        "family_expenses",
        sa.Column("added_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_family_expenses_added_by_user_id",
        "family_expenses",
        "users",
        ["added_by_user_id"],
        ["id"],
    )
    op.add_column(
        "family_expenses",
        sa.Column("expense_made_for_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_family_expenses_expense_made_for_user_id",
        "family_expenses",
        "users",
        ["expense_made_for_user_id"],
        ["id"],
    )

    op.add_column(
        "personal_expenses",
        sa.Column("expense_made_for_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_personal_expenses_expense_made_for_user_id",
        "personal_expenses",
        "users",
        ["expense_made_for_user_id"],
        ["id"],
    )

    op.add_column(
        "family_expense_logs",
        sa.Column("expense_made_for_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_family_expense_logs_expense_made_for_user_id",
        "family_expense_logs",
        "users",
        ["expense_made_for_user_id"],
        ["id"],
    )

    op.add_column(
        "personal_expense_logs",
        sa.Column("expense_made_for_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_personal_expense_logs_expense_made_for_user_id",
        "personal_expense_logs",
        "users",
        ["expense_made_for_user_id"],
        ["id"],
    )

    # 4. Perform Data Migration
    bind = op.get_bind()
    families = bind.execute(sa.text("SELECT id FROM families")).fetchall()
    for row in families:
        family_id = row[0]
        
        # Create 'Other' Income Category
        income_cat_id = uuid6.uuid7()
        bind.execute(
            sa.text(
                "INSERT INTO family_income_categories (id, family_id, category_name, created_at, updated_at) "
                "VALUES (:id, :family_id, 'Other', NOW(), NOW())"
            ),
            {"id": income_cat_id, "family_id": family_id}
        )

        # Update existing incomes to 'Other'
        bind.execute(
            sa.text(
                "UPDATE recurring_incomes SET category_id = :cat_id "
                "WHERE category_id IS NULL AND (id IN (SELECT income_id FROM recurring_income_family_splits WHERE family_id = :family_id) "
                "OR user_id IN (SELECT user_id FROM user_family_links WHERE family_id = :family_id))"
            ),
            {"cat_id": income_cat_id, "family_id": family_id}
        )
        bind.execute(
            sa.text("UPDATE family_income_logs SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": income_cat_id, "family_id": family_id}
        )
        bind.execute(
            sa.text("UPDATE personal_income_logs SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": income_cat_id, "family_id": family_id}
        )

        # Ensure 'Other' Expense Category exists
        expense_cat_row = bind.execute(
            sa.text("SELECT id FROM family_expense_categories WHERE family_id = :family_id AND category_name = 'Other'"),
            {"family_id": family_id}
        ).fetchone()

        if expense_cat_row:
            expense_cat_id = expense_cat_row[0]
        else:
            expense_cat_id = uuid6.uuid7()
            bind.execute(
                sa.text(
                    "INSERT INTO family_expense_categories (id, family_id, category_name, created_at, updated_at) "
                    "VALUES (:id, :family_id, 'Other', NOW(), NOW())"
                ),
                {"id": expense_cat_id, "family_id": family_id}
            )

        # Update existing expenses to 'Other'
        bind.execute(
            sa.text("UPDATE family_expenses SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": expense_cat_id, "family_id": family_id}
        )
        bind.execute(
            sa.text("UPDATE personal_expenses SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": expense_cat_id, "family_id": family_id}
        )
        bind.execute(
            sa.text("UPDATE family_expense_logs SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": expense_cat_id, "family_id": family_id}
        )
        bind.execute(
            sa.text("UPDATE personal_expense_logs SET category_id = :cat_id WHERE category_id IS NULL AND family_id = :family_id"),
            {"cat_id": expense_cat_id, "family_id": family_id}
        )


def downgrade() -> None:
    # Drop FK and column for personal_expense_logs
    op.drop_constraint("fk_personal_expense_logs_expense_made_for_user_id", "personal_expense_logs", type_="foreignkey")
    op.drop_column("personal_expense_logs", "expense_made_for_user_id")

    # Drop FK and column for family_expense_logs
    op.drop_constraint("fk_family_expense_logs_expense_made_for_user_id", "family_expense_logs", type_="foreignkey")
    op.drop_column("family_expense_logs", "expense_made_for_user_id")

    # Drop FK and column for personal_expenses
    op.drop_constraint("fk_personal_expenses_expense_made_for_user_id", "personal_expenses", type_="foreignkey")
    op.drop_column("personal_expenses", "expense_made_for_user_id")

    # Drop FKs and columns for family_expenses
    op.drop_constraint("fk_family_expenses_expense_made_for_user_id", "family_expenses", type_="foreignkey")
    op.drop_constraint("fk_family_expenses_added_by_user_id", "family_expenses", type_="foreignkey")
    op.drop_column("family_expenses", "expense_made_for_user_id")
    op.drop_column("family_expenses", "added_by_user_id")

    # Drop FK and column for personal_income_logs
    op.drop_constraint("fk_personal_income_logs_category_id", "personal_income_logs", type_="foreignkey")
    op.drop_column("personal_income_logs", "category_id")

    # Drop FK and column for family_income_logs
    op.drop_constraint("fk_family_income_logs_category_id", "family_income_logs", type_="foreignkey")
    op.drop_column("family_income_logs", "category_id")

    # Drop FKs and columns for recurring_incomes
    op.drop_constraint("fk_recurring_incomes_category_id", "recurring_incomes", type_="foreignkey")
    op.drop_constraint("fk_recurring_incomes_added_by_user_id", "recurring_incomes", type_="foreignkey")
    op.drop_column("recurring_incomes", "category_id")
    op.drop_column("recurring_incomes", "added_by_user_id")

    # Drop index and table family_income_categories
    op.drop_index("ix_family_income_categories_family_id", table_name="family_income_categories")
    op.drop_table("family_income_categories")
