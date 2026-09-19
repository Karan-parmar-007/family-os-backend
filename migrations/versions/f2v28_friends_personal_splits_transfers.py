"""Friends, multi-person personal splits, transfer nullability.

Revision ID: f2v28friendssplits
Revises: f2v27dedupesplitplans
"""

from typing import Sequence, Union

import secrets
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "f2v28friendssplits"
down_revision: Union[str, Sequence[str], None] = "f2v27dedupesplitplans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _unique_friend_code(bind) -> str:
    while True:
        candidate = f"{secrets.randbelow(100000000):08d}"
        exists = bind.execute(
            sa.text("SELECT 1 FROM users WHERE friend_code = :code LIMIT 1"),
            {"code": candidate},
        ).first()
        if exists is None:
            return candidate


def upgrade() -> None:
    # --- users.friend_code ---
    op.add_column("users", sa.Column("friend_code", sa.String(length=8), nullable=True))
    bind = op.get_bind()
    users_missing = list(
        bind.execute(sa.text("SELECT id FROM users WHERE friend_code IS NULL")).fetchall()
    )
    for (user_id,) in users_missing:
        code = _unique_friend_code(bind)
        bind.execute(
            sa.text("UPDATE users SET friend_code = :code WHERE id = :id"),
            {"code": code, "id": str(user_id)},
        )
    op.alter_column("users", "friend_code", nullable=False)
    op.create_index(op.f("ix_users_friend_code"), "users", ["friend_code"], unique=True)

    # --- friendships ---
    op.create_table(
        "friendships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_a_id", sa.Uuid(), nullable=False),
        sa.Column("user_b_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
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
        sa.ForeignKeyConstraint(["user_a_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_b_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_friendships_user_pair"),
    )
    op.create_index(op.f("ix_friendships_user_a_id"), "friendships", ["user_a_id"])
    op.create_index(op.f("ix_friendships_user_b_id"), "friendships", ["user_b_id"])
    op.create_index(op.f("ix_friendships_status"), "friendships", ["status"])

    # --- log_funding_sources.user_id ---
    op.add_column(
        "log_funding_sources",
        sa.Column("user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_log_funding_sources_user_id_users",
        "log_funding_sources",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_log_funding_sources_user_id"),
        "log_funding_sources",
        ["user_id"],
    )

    # --- recurring personal splits ---
    op.create_table(
        "recurring_income_personal_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("income_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["income_id"], ["recurring_incomes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "income_id", "user_id", name="uq_recurring_income_personal_splits_income_user"
        ),
    )
    op.create_index(
        op.f("ix_recurring_income_personal_splits_income_id"),
        "recurring_income_personal_splits",
        ["income_id"],
    )
    op.create_index(
        op.f("ix_recurring_income_personal_splits_user_id"),
        "recurring_income_personal_splits",
        ["user_id"],
    )

    op.create_table(
        "recurring_expense_personal_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["expense_id"], ["recurring_expenses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "expense_id", "user_id", name="uq_recurring_expense_personal_splits_expense_user"
        ),
    )
    op.create_index(
        op.f("ix_recurring_expense_personal_splits_expense_id"),
        "recurring_expense_personal_splits",
        ["expense_id"],
    )
    op.create_index(
        op.f("ix_recurring_expense_personal_splits_user_id"),
        "recurring_expense_personal_splits",
        ["user_id"],
    )

    # Backfill personal splits from existing personal_savings_amount
    income_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, user_id, personal_savings_amount
                FROM recurring_incomes
                WHERE personal_savings_amount IS NOT NULL AND personal_savings_amount > 0
                """
            )
        ).fetchall()
    )
    for income_id, user_id, amount in income_rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO recurring_income_personal_splits (id, income_id, user_id, amount)
                VALUES (:id, :income_id, :user_id, :amount)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "income_id": str(income_id),
                "user_id": str(user_id),
                "amount": amount,
            },
        )

    expense_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, user_id, personal_savings_amount
                FROM recurring_expenses
                WHERE personal_savings_amount IS NOT NULL AND personal_savings_amount > 0
                """
            )
        ).fetchall()
    )
    for expense_id, user_id, amount in expense_rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO recurring_expense_personal_splits (id, expense_id, user_id, amount)
                VALUES (:id, :expense_id, :user_id, :amount)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "expense_id": str(expense_id),
                "user_id": str(user_id),
                "amount": amount,
            },
        )

    # --- transfers: nullable family_id for personal↔personal ---
    op.alter_column("transfers", "family_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.alter_column("transfers", "family_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_index(
        op.f("ix_recurring_expense_personal_splits_user_id"),
        table_name="recurring_expense_personal_splits",
    )
    op.drop_index(
        op.f("ix_recurring_expense_personal_splits_expense_id"),
        table_name="recurring_expense_personal_splits",
    )
    op.drop_table("recurring_expense_personal_splits")

    op.drop_index(
        op.f("ix_recurring_income_personal_splits_user_id"),
        table_name="recurring_income_personal_splits",
    )
    op.drop_index(
        op.f("ix_recurring_income_personal_splits_income_id"),
        table_name="recurring_income_personal_splits",
    )
    op.drop_table("recurring_income_personal_splits")

    op.drop_index(op.f("ix_log_funding_sources_user_id"), table_name="log_funding_sources")
    op.drop_constraint(
        "fk_log_funding_sources_user_id_users",
        "log_funding_sources",
        type_="foreignkey",
    )
    op.drop_column("log_funding_sources", "user_id")

    op.drop_index(op.f("ix_friendships_status"), table_name="friendships")
    op.drop_index(op.f("ix_friendships_user_b_id"), table_name="friendships")
    op.drop_index(op.f("ix_friendships_user_a_id"), table_name="friendships")
    op.drop_table("friendships")

    op.drop_index(op.f("ix_users_friend_code"), table_name="users")
    op.drop_column("users", "friend_code")
