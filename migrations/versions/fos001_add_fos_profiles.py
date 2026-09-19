"""add fos_profiles table

Revision ID: fos001_profiles
Revises: (latest)
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers
revision = 'fos001_profiles'
down_revision = "f2v29sessionstart"  # set to latest migration id
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fos_profiles',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('sso_user_id', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('email', sa.String(320), nullable=False, unique=True, index=True),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('personal_currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('timezone', sa.String(64), nullable=False, server_default='Asia/Kolkata'),
        sa.Column('personal_code', sa.String(8), nullable=False, unique=True),
        sa.Column('max_family_memberships', sa.Integer, nullable=False, server_default='2'),
        sa.Column('setup_completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('vault_password_hash', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_fos_profiles_personal_code', 'fos_profiles', ['personal_code'])


def downgrade() -> None:
    op.drop_table('fos_profiles')
