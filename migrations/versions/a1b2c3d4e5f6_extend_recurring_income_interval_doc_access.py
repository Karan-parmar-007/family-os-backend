"""extend recurring income: interval fields, earned_by, doc access tables, relaxed log amounts

Revision ID: a1b2c3d4e5f6
Revises: 76cbbb02fded
Create Date: 2026-06-27 18:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '76cbbb02fded'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # -----------------------------------------------------------------------
    # 1. family_recurring_incomes — new columns
    # -----------------------------------------------------------------------
    op.add_column(
        'family_recurring_incomes',
        sa.Column('repeat_interval_days', sa.Integer(), nullable=True),
    )
    op.add_column(
        'family_recurring_incomes',
        sa.Column('repeat_interval_months', sa.Integer(), nullable=True),
    )
    op.add_column(
        'family_recurring_incomes',
        sa.Column('repeat_interval_years', sa.Integer(), nullable=True),
    )
    op.add_column(
        'family_recurring_incomes',
        sa.Column('earned_by_user_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_family_recurring_incomes_earned_by_user_id',
        'family_recurring_incomes',
        'users',
        ['earned_by_user_id'],
        ['id'],
    )

    # -----------------------------------------------------------------------
    # 2. family_recurring_income_doc_access — new table
    # -----------------------------------------------------------------------
    op.create_table(
        'family_recurring_income_doc_access',
        sa.Column('income_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['income_id'], ['family_recurring_incomes.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('income_id', 'user_id'),
    )

    # -----------------------------------------------------------------------
    # 3. family_income_log_doc_access — new table
    # -----------------------------------------------------------------------
    op.create_table(
        'family_income_log_doc_access',
        sa.Column('log_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['log_id'], ['family_income_logs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('log_id', 'user_id'),
    )

    # -----------------------------------------------------------------------
    # 4. family_income_logs — make family_amount nullable
    #    (previously NOT NULL with default 0; now optional — callers may omit
    #     the split and only record total_amount)
    # -----------------------------------------------------------------------
    op.alter_column(
        'family_income_logs',
        'family_amount',
        existing_type=sa.Numeric(precision=12, scale=2),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Reverse family_income_logs nullable change
    op.alter_column(
        'family_income_logs',
        'family_amount',
        existing_type=sa.Numeric(precision=12, scale=2),
        nullable=False,
        server_default=sa.text('0'),
    )

    # Drop new tables
    op.drop_table('family_income_log_doc_access')
    op.drop_table('family_recurring_income_doc_access')

    # Drop new FK + columns from family_recurring_incomes
    op.drop_constraint(
        'fk_family_recurring_incomes_earned_by_user_id',
        'family_recurring_incomes',
        type_='foreignkey',
    )
    op.drop_column('family_recurring_incomes', 'earned_by_user_id')
    op.drop_column('family_recurring_incomes', 'repeat_interval_years')
    op.drop_column('family_recurring_incomes', 'repeat_interval_months')
    op.drop_column('family_recurring_incomes', 'repeat_interval_days')
