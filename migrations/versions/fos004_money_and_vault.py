"""Add fos_money_rules, fos_money_events, fos_debts, fos_vault_items

Revision ID: fos004_money_and_vault
Revises: fos003_membership
Create Date: 2026-09-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'fos004_money_and_vault'
down_revision: Union[str, None] = 'fos003_membership'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update families
    op.add_column('families', sa.Column('vault_password_hash', sa.String(255), nullable=True))

    # 2. Update family_assets
    op.add_column('family_assets', sa.Column('quantity_label', sa.Text(), nullable=True))

    # 3. Create fos_money_rules
    op.create_table(
        'fos_money_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('frequency', sa.String(32), nullable=False, server_default='MONTHLY'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('let_everyone_edit', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('insurance_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('debt_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 4. Create fos_money_rule_parties
    op.create_table(
        'fos_money_rule_parties',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fos_money_rules.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('party_type', sa.String(16), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 5. Create fos_money_events
    op.create_table(
        'fos_money_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fos_money_rules.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('let_everyone_edit', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 6. Create fos_money_event_parties
    op.create_table(
        'fos_money_event_parties',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fos_money_events.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('party_type', sa.String(16), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 7. Create fos_debts
    op.create_table(
        'fos_debts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('owner_type', sa.String(16), nullable=False),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('has_emi', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('add_emi_to_paid', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('linked_rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fos_money_rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('let_everyone_edit', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='OPEN'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 8. Create fos_vault_items
    op.create_table(
        'fos_vault_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('for_party_type', sa.String(16), nullable=False),
        sa.Column('for_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('is_protected', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('ciphertext', sa.Text(), nullable=True),
        sa.Column('nonce', sa.String(64), nullable=True),
        sa.Column('file_key', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('fos_vault_items')
    op.drop_table('fos_debts')
    op.drop_table('fos_money_event_parties')
    op.drop_table('fos_money_events')
    op.drop_table('fos_money_rule_parties')
    op.drop_table('fos_money_rules')
    op.drop_column('family_assets', 'quantity_label')
    op.drop_column('families', 'vault_password_hash')
