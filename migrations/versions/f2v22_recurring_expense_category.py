"""Add category_id to recurring_expenses."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v22recurringexpensecategory"
down_revision: Union[str, Sequence[str], None] = "f2v21categoriesandformoptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recurring_expenses",
        sa.Column("category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_recurring_expenses_category_id",
        "recurring_expenses",
        "family_expense_categories",
        ["category_id"],
        ["id"],
    )

    bind = op.get_bind()
    families = bind.execute(sa.text("SELECT id FROM families")).fetchall()
    for row in families:
        family_id = row[0]
        expense_cat_row = bind.execute(
            sa.text(
                "SELECT id FROM family_expense_categories "
                "WHERE family_id = :family_id AND category_name = 'Other'"
            ),
            {"family_id": family_id},
        ).fetchone()
        if not expense_cat_row:
            continue
        expense_cat_id = expense_cat_row[0]
        bind.execute(
            sa.text(
                "UPDATE recurring_expenses SET category_id = :cat_id "
                "WHERE category_id IS NULL AND ("
                "id IN (SELECT expense_id FROM recurring_expense_family_splits WHERE family_id = :family_id) "
                "OR user_id IN (SELECT user_id FROM user_family_links WHERE family_id = :family_id)"
                ")"
            ),
            {"cat_id": expense_cat_id, "family_id": family_id},
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_recurring_expenses_category_id", "recurring_expenses", type_="foreignkey"
    )
    op.drop_column("recurring_expenses", "category_id")
