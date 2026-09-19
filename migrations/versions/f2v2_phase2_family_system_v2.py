"""Family System V2 phase 2: sub-families, ledger, scope columns

Revision ID: f2v2phase2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-30 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2v2phase2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table('sub_families',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('visibility', sa.String(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('auto_transfer_enabled', sa.Boolean(), nullable=False),
        sa.Column('auto_transfer_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('auto_transfer_every', sa.String(), nullable=True),
        sa.Column('auto_transfer_next_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('auto_transfer_source', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sub_families_family_id'), 'sub_families', ['family_id'], unique=False)
    op.create_table('sub_family_members',
        sa.Column('sub_family_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('sub_family_id', 'user_id'),
    )
    op.create_table('sub_family_invites',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=False),
        sa.Column('invited_user_id', sa.Uuid(), nullable=False),
        sa.Column('invited_by', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id']),
        sa.ForeignKeyConstraint(['invited_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sub_family_invites_sub_family_id'), 'sub_family_invites', ['sub_family_id'], unique=False)
    op.add_column('family_total_savings', sa.Column('origin_amount', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('personal_total_savings', sa.Column('origin_amount', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('personal_total_savings', sa.Column('keep_in_family_only', sa.Boolean(), server_default='true', nullable=False))
    op.execute("UPDATE family_total_savings SET origin_amount = total_savings WHERE origin_amount = 0")
    op.execute("UPDATE personal_total_savings SET origin_amount = total_savings WHERE origin_amount = 0")
    op.create_table('sub_family_total_savings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=False),
        sa.Column('origin_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_savings', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sub_family_id'),
    )
    op.create_index(op.f('ix_sub_family_total_savings_family_id'), 'sub_family_total_savings', ['family_id'], unique=False)
    op.create_table('user_global_personal_savings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('origin_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_savings', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_table('savings_ledger',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pool_type', sa.String(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=True),
        sa.Column('sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_savings_ledger_family_id'), 'savings_ledger', ['family_id'], unique=False)
    op.create_index(op.f('ix_savings_ledger_sub_family_id'), 'savings_ledger', ['sub_family_id'], unique=False)
    op.create_index(op.f('ix_savings_ledger_user_id'), 'savings_ledger', ['user_id'], unique=False)
    op.execute("""
        INSERT INTO savings_ledger (
            id, pool_type, family_id, amount, direction, source_type, occurred_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            'FAMILY',
            ft.family_id,
            ft.origin_amount,
            'IN',
            'ORIGIN',
            ft.created_at,
            ft.created_at,
            ft.updated_at
        FROM family_total_savings ft
        WHERE ft.origin_amount > 0
          AND NOT EXISTS (
            SELECT 1 FROM savings_ledger sl
            WHERE sl.pool_type = 'FAMILY'
              AND sl.family_id = ft.family_id
              AND sl.source_type = 'ORIGIN'
          )
    """)
    op.execute("""
        INSERT INTO savings_ledger (
            id, pool_type, family_id, user_id, amount, direction, source_type, occurred_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            'PERSONAL',
            pt.family_id,
            pt.user_id,
            pt.origin_amount,
            'IN',
            'ORIGIN',
            pt.created_at,
            pt.created_at,
            pt.updated_at
        FROM personal_total_savings pt
        WHERE pt.origin_amount > 0
          AND NOT EXISTS (
            SELECT 1 FROM savings_ledger sl
            WHERE sl.pool_type = 'PERSONAL'
              AND sl.family_id = pt.family_id
              AND sl.user_id = pt.user_id
              AND sl.source_type = 'ORIGIN'
          )
    """)
    op.add_column('family_assets', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_assets', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_assets_sub_family_id'), 'family_assets', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_assets_sub_family_id_sub_families'), 'family_assets', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_assets', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_assets', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_assets_sub_family_id'), 'personal_assets', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_assets_sub_family_id_sub_families'), 'personal_assets', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_debts', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_debts', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_debts_sub_family_id'), 'family_debts', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_debts_sub_family_id_sub_families'), 'family_debts', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_debts', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_debts', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_debts_sub_family_id'), 'personal_debts', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_debts_sub_family_id_sub_families'), 'personal_debts', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_insurances', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_insurances', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_insurances_sub_family_id'), 'family_insurances', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_insurances_sub_family_id_sub_families'), 'family_insurances', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_insurances', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_insurances', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_insurances_sub_family_id'), 'personal_insurances', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_insurances_sub_family_id_sub_families'), 'personal_insurances', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_recurring_incomes', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_recurring_incomes', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_recurring_incomes_sub_family_id'), 'family_recurring_incomes', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_recurring_incomes_sub_family_id_sub_families'), 'family_recurring_incomes', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_recurring_incomes', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_recurring_incomes', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_recurring_incomes_sub_family_id'), 'personal_recurring_incomes', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_recurring_incomes_sub_family_id_sub_families'), 'personal_recurring_incomes', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_income_logs', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_income_logs', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_income_logs_sub_family_id'), 'family_income_logs', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_income_logs_sub_family_id_sub_families'), 'family_income_logs', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_income_logs', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_income_logs', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_income_logs_sub_family_id'), 'personal_income_logs', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_income_logs_sub_family_id_sub_families'), 'personal_income_logs', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_expenses', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_expenses', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_expenses_sub_family_id'), 'family_expenses', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_expenses_sub_family_id_sub_families'), 'family_expenses', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_expenses', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_expenses', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_expenses_sub_family_id'), 'personal_expenses', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_expenses_sub_family_id_sub_families'), 'personal_expenses', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_expense_logs', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_expense_logs', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_expense_logs_sub_family_id'), 'family_expense_logs', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_expense_logs_sub_family_id_sub_families'), 'family_expense_logs', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_expense_logs', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_expense_logs', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_expense_logs_sub_family_id'), 'personal_expense_logs', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_expense_logs_sub_family_id_sub_families'), 'personal_expense_logs', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_savings_plans', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_savings_plans', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_savings_plans_sub_family_id'), 'family_savings_plans', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_savings_plans_sub_family_id_sub_families'), 'family_savings_plans', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_savings_plans', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_savings_plans', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_savings_plans_sub_family_id'), 'personal_savings_plans', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_savings_plans_sub_family_id_sub_families'), 'personal_savings_plans', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_goals', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_goals', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_goals_sub_family_id'), 'family_goals', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_goals_sub_family_id_sub_families'), 'family_goals', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_goals', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_goals', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_goals_sub_family_id'), 'personal_goals', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_goals_sub_family_id_sub_families'), 'personal_goals', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_savings_logs', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_savings_logs', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_savings_logs_sub_family_id'), 'personal_savings_logs', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_savings_logs_sub_family_id_sub_families'), 'personal_savings_logs', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_savings_plan_contributions', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_savings_plan_contributions', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_savings_plan_contributions_sub_family_id'), 'family_savings_plan_contributions', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_savings_plan_contributions_sub_family_id_sub_families'), 'family_savings_plan_contributions', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_savings_plan_contributions', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_savings_plan_contributions', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_savings_plan_contributions_sub_family_id'), 'personal_savings_plan_contributions', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_savings_plan_contributions_sub_family_id_sub_families'), 'personal_savings_plan_contributions', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('family_goal_contributions', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('family_goal_contributions', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_family_goal_contributions_sub_family_id'), 'family_goal_contributions', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_family_goal_contributions_sub_family_id_sub_families'), 'family_goal_contributions', 'sub_families', ['sub_family_id'], ['id'])
    op.add_column('personal_goal_contributions', sa.Column('scope_type', sa.String(), server_default='FAMILY', nullable=False))
    op.add_column('personal_goal_contributions', sa.Column('sub_family_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_personal_goal_contributions_sub_family_id'), 'personal_goal_contributions', ['sub_family_id'], unique=False)
    op.create_foreign_key(op.f('fk_personal_goal_contributions_sub_family_id_sub_families'), 'personal_goal_contributions', 'sub_families', ['sub_family_id'], ['id'])
    op.create_table('entity_subfamily_shares',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=False),
        sa.Column('shared_by', sa.Uuid(), nullable=False),
        sa.Column('share_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('share_logs', sa.Boolean(), nullable=False),
        sa.Column('share_docs', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['shared_by'], ['users.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_entity_subfamily_shares_sub_family_id'), 'entity_subfamily_shares', ['sub_family_id'], unique=False)
    op.create_table('personal_savings_subfamily_share',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=False),
        sa.Column('initial_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('share_recurring', sa.Boolean(), nullable=False),
        sa.Column('share_future_logs', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_personal_savings_subfamily_share_family_id'), 'personal_savings_subfamily_share', ['family_id'], unique=False)
    op.create_index(op.f('ix_personal_savings_subfamily_share_sub_family_id'), 'personal_savings_subfamily_share', ['sub_family_id'], unique=False)
    op.create_table('transfers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('from_scope', sa.String(), nullable=False),
        sa.Column('from_sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('from_user_id', sa.Uuid(), nullable=True),
        sa.Column('to_scope', sa.String(), nullable=False),
        sa.Column('to_sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('to_user_id', sa.Uuid(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('source_entity_id', sa.Uuid(), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('remaining_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('transfer_logs', sa.Boolean(), nullable=False),
        sa.Column('transfer_docs', sa.Boolean(), nullable=False),
        sa.Column('is_recurring', sa.Boolean(), nullable=False),
        sa.Column('recurring_every', sa.String(), nullable=True),
        sa.Column('next_run_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['from_sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['from_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['to_sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['to_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transfers_family_id'), 'transfers', ['family_id'], unique=False)
    op.create_table('scheduled_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('job_type', sa.String(), nullable=False),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('assigned_user_id', sa.Uuid(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('period_key', sa.String(), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requires_confirmation', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('delay_days', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_ledger_id', sa.Uuid(), nullable=True),
        sa.Column('notification_id', sa.Uuid(), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_type', 'source_id', 'period_key'),
    )
    op.create_index(op.f('ix_scheduled_jobs_family_id'), 'scheduled_jobs', ['family_id'], unique=False)
    op.create_table('notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=True),
        sa.Column('sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('related_job_id', sa.Uuid(), nullable=True),
        sa.Column('related_entity_type', sa.String(), nullable=True),
        sa.Column('related_entity_id', sa.Uuid(), nullable=True),
        sa.Column('allowed_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('action_taken', sa.String(), nullable=True),
        sa.Column('actioned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['related_job_id'], ['scheduled_jobs.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('bounced_payments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('sub_family_id', sa.Uuid(), nullable=True),
        sa.Column('debt_id', sa.Uuid(), nullable=False),
        sa.Column('debt_scope', sa.String(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('period_key', sa.String(), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['job_id'], ['scheduled_jobs.id']),
        sa.ForeignKeyConstraint(['sub_family_id'], ['sub_families.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('debt_scope', 'debt_id', 'period_key'),
    )
    op.create_index(op.f('ix_bounced_payments_family_id'), 'bounced_payments', ['family_id'], unique=False)


def downgrade() -> None:

    op.drop_index(op.f('ix_bounced_payments_family_id'), table_name='bounced_payments')
    op.drop_table('bounced_payments')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_scheduled_jobs_family_id'), table_name='scheduled_jobs')
    op.drop_table('scheduled_jobs')
    op.drop_index(op.f('ix_transfers_family_id'), table_name='transfers')
    op.drop_table('transfers')
    op.drop_index(op.f('ix_personal_savings_subfamily_share_sub_family_id'), table_name='personal_savings_subfamily_share')
    op.drop_index(op.f('ix_personal_savings_subfamily_share_family_id'), table_name='personal_savings_subfamily_share')
    op.drop_table('personal_savings_subfamily_share')
    op.drop_index(op.f('ix_entity_subfamily_shares_sub_family_id'), table_name='entity_subfamily_shares')
    op.drop_table('entity_subfamily_shares')
    op.drop_constraint(op.f('fk_personal_goal_contributions_sub_family_id_sub_families'), 'personal_goal_contributions', type_='foreignkey')
    op.drop_index(op.f('ix_personal_goal_contributions_sub_family_id'), table_name='personal_goal_contributions')
    op.drop_column('personal_goal_contributions', 'sub_family_id')
    op.drop_column('personal_goal_contributions', 'scope_type')
    op.drop_constraint(op.f('fk_family_goal_contributions_sub_family_id_sub_families'), 'family_goal_contributions', type_='foreignkey')
    op.drop_index(op.f('ix_family_goal_contributions_sub_family_id'), table_name='family_goal_contributions')
    op.drop_column('family_goal_contributions', 'sub_family_id')
    op.drop_column('family_goal_contributions', 'scope_type')
    op.drop_constraint(op.f('fk_personal_savings_plan_contributions_sub_family_id_sub_families'), 'personal_savings_plan_contributions', type_='foreignkey')
    op.drop_index(op.f('ix_personal_savings_plan_contributions_sub_family_id'), table_name='personal_savings_plan_contributions')
    op.drop_column('personal_savings_plan_contributions', 'sub_family_id')
    op.drop_column('personal_savings_plan_contributions', 'scope_type')
    op.drop_constraint(op.f('fk_family_savings_plan_contributions_sub_family_id_sub_families'), 'family_savings_plan_contributions', type_='foreignkey')
    op.drop_index(op.f('ix_family_savings_plan_contributions_sub_family_id'), table_name='family_savings_plan_contributions')
    op.drop_column('family_savings_plan_contributions', 'sub_family_id')
    op.drop_column('family_savings_plan_contributions', 'scope_type')
    op.drop_constraint(op.f('fk_personal_savings_logs_sub_family_id_sub_families'), 'personal_savings_logs', type_='foreignkey')
    op.drop_index(op.f('ix_personal_savings_logs_sub_family_id'), table_name='personal_savings_logs')
    op.drop_column('personal_savings_logs', 'sub_family_id')
    op.drop_column('personal_savings_logs', 'scope_type')
    op.drop_constraint(op.f('fk_personal_goals_sub_family_id_sub_families'), 'personal_goals', type_='foreignkey')
    op.drop_index(op.f('ix_personal_goals_sub_family_id'), table_name='personal_goals')
    op.drop_column('personal_goals', 'sub_family_id')
    op.drop_column('personal_goals', 'scope_type')
    op.drop_constraint(op.f('fk_family_goals_sub_family_id_sub_families'), 'family_goals', type_='foreignkey')
    op.drop_index(op.f('ix_family_goals_sub_family_id'), table_name='family_goals')
    op.drop_column('family_goals', 'sub_family_id')
    op.drop_column('family_goals', 'scope_type')
    op.drop_constraint(op.f('fk_personal_savings_plans_sub_family_id_sub_families'), 'personal_savings_plans', type_='foreignkey')
    op.drop_index(op.f('ix_personal_savings_plans_sub_family_id'), table_name='personal_savings_plans')
    op.drop_column('personal_savings_plans', 'sub_family_id')
    op.drop_column('personal_savings_plans', 'scope_type')
    op.drop_constraint(op.f('fk_family_savings_plans_sub_family_id_sub_families'), 'family_savings_plans', type_='foreignkey')
    op.drop_index(op.f('ix_family_savings_plans_sub_family_id'), table_name='family_savings_plans')
    op.drop_column('family_savings_plans', 'sub_family_id')
    op.drop_column('family_savings_plans', 'scope_type')
    op.drop_constraint(op.f('fk_personal_expense_logs_sub_family_id_sub_families'), 'personal_expense_logs', type_='foreignkey')
    op.drop_index(op.f('ix_personal_expense_logs_sub_family_id'), table_name='personal_expense_logs')
    op.drop_column('personal_expense_logs', 'sub_family_id')
    op.drop_column('personal_expense_logs', 'scope_type')
    op.drop_constraint(op.f('fk_family_expense_logs_sub_family_id_sub_families'), 'family_expense_logs', type_='foreignkey')
    op.drop_index(op.f('ix_family_expense_logs_sub_family_id'), table_name='family_expense_logs')
    op.drop_column('family_expense_logs', 'sub_family_id')
    op.drop_column('family_expense_logs', 'scope_type')
    op.drop_constraint(op.f('fk_personal_expenses_sub_family_id_sub_families'), 'personal_expenses', type_='foreignkey')
    op.drop_index(op.f('ix_personal_expenses_sub_family_id'), table_name='personal_expenses')
    op.drop_column('personal_expenses', 'sub_family_id')
    op.drop_column('personal_expenses', 'scope_type')
    op.drop_constraint(op.f('fk_family_expenses_sub_family_id_sub_families'), 'family_expenses', type_='foreignkey')
    op.drop_index(op.f('ix_family_expenses_sub_family_id'), table_name='family_expenses')
    op.drop_column('family_expenses', 'sub_family_id')
    op.drop_column('family_expenses', 'scope_type')
    op.drop_constraint(op.f('fk_personal_income_logs_sub_family_id_sub_families'), 'personal_income_logs', type_='foreignkey')
    op.drop_index(op.f('ix_personal_income_logs_sub_family_id'), table_name='personal_income_logs')
    op.drop_column('personal_income_logs', 'sub_family_id')
    op.drop_column('personal_income_logs', 'scope_type')
    op.drop_constraint(op.f('fk_family_income_logs_sub_family_id_sub_families'), 'family_income_logs', type_='foreignkey')
    op.drop_index(op.f('ix_family_income_logs_sub_family_id'), table_name='family_income_logs')
    op.drop_column('family_income_logs', 'sub_family_id')
    op.drop_column('family_income_logs', 'scope_type')
    op.drop_constraint(op.f('fk_personal_recurring_incomes_sub_family_id_sub_families'), 'personal_recurring_incomes', type_='foreignkey')
    op.drop_index(op.f('ix_personal_recurring_incomes_sub_family_id'), table_name='personal_recurring_incomes')
    op.drop_column('personal_recurring_incomes', 'sub_family_id')
    op.drop_column('personal_recurring_incomes', 'scope_type')
    op.drop_constraint(op.f('fk_family_recurring_incomes_sub_family_id_sub_families'), 'family_recurring_incomes', type_='foreignkey')
    op.drop_index(op.f('ix_family_recurring_incomes_sub_family_id'), table_name='family_recurring_incomes')
    op.drop_column('family_recurring_incomes', 'sub_family_id')
    op.drop_column('family_recurring_incomes', 'scope_type')
    op.drop_constraint(op.f('fk_personal_insurances_sub_family_id_sub_families'), 'personal_insurances', type_='foreignkey')
    op.drop_index(op.f('ix_personal_insurances_sub_family_id'), table_name='personal_insurances')
    op.drop_column('personal_insurances', 'sub_family_id')
    op.drop_column('personal_insurances', 'scope_type')
    op.drop_constraint(op.f('fk_family_insurances_sub_family_id_sub_families'), 'family_insurances', type_='foreignkey')
    op.drop_index(op.f('ix_family_insurances_sub_family_id'), table_name='family_insurances')
    op.drop_column('family_insurances', 'sub_family_id')
    op.drop_column('family_insurances', 'scope_type')
    op.drop_constraint(op.f('fk_personal_debts_sub_family_id_sub_families'), 'personal_debts', type_='foreignkey')
    op.drop_index(op.f('ix_personal_debts_sub_family_id'), table_name='personal_debts')
    op.drop_column('personal_debts', 'sub_family_id')
    op.drop_column('personal_debts', 'scope_type')
    op.drop_constraint(op.f('fk_family_debts_sub_family_id_sub_families'), 'family_debts', type_='foreignkey')
    op.drop_index(op.f('ix_family_debts_sub_family_id'), table_name='family_debts')
    op.drop_column('family_debts', 'sub_family_id')
    op.drop_column('family_debts', 'scope_type')
    op.drop_constraint(op.f('fk_personal_assets_sub_family_id_sub_families'), 'personal_assets', type_='foreignkey')
    op.drop_index(op.f('ix_personal_assets_sub_family_id'), table_name='personal_assets')
    op.drop_column('personal_assets', 'sub_family_id')
    op.drop_column('personal_assets', 'scope_type')
    op.drop_constraint(op.f('fk_family_assets_sub_family_id_sub_families'), 'family_assets', type_='foreignkey')
    op.drop_index(op.f('ix_family_assets_sub_family_id'), table_name='family_assets')
    op.drop_column('family_assets', 'sub_family_id')
    op.drop_column('family_assets', 'scope_type')
    op.drop_index(op.f('ix_savings_ledger_user_id'), table_name='savings_ledger')
    op.drop_index(op.f('ix_savings_ledger_sub_family_id'), table_name='savings_ledger')
    op.drop_index(op.f('ix_savings_ledger_family_id'), table_name='savings_ledger')
    op.drop_table('savings_ledger')
    op.drop_table('user_global_personal_savings')
    op.drop_index(op.f('ix_sub_family_total_savings_family_id'), table_name='sub_family_total_savings')
    op.drop_table('sub_family_total_savings')
    op.drop_column('personal_total_savings', 'keep_in_family_only')
    op.drop_column('personal_total_savings', 'origin_amount')
    op.drop_column('family_total_savings', 'origin_amount')
    op.drop_index(op.f('ix_sub_family_invites_sub_family_id'), table_name='sub_family_invites')
    op.drop_table('sub_family_invites')
    op.drop_table('sub_family_members')
    op.drop_index(op.f('ix_sub_families_family_id'), table_name='sub_families')
    op.drop_table('sub_families')
