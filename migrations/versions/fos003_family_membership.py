"""add membership_code, link_code, timezone to families, and add join_requests & invites tables

Revision ID: fos003_membership
Revises: fos002_currencies
Create Date: 2026-09-09
"""
import secrets
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'fos003_membership'
down_revision = 'fos002_currencies'
branch_labels = None
depends_on = None


def _gen_code() -> str:
    return f"{secrets.randbelow(100000000):08d}"


def upgrade() -> None:
    # 1. Add columns to families
    op.add_column('families', sa.Column('membership_code', sa.String(8), nullable=True))
    op.add_column('families', sa.Column('link_code', sa.String(8), nullable=True))
    op.add_column('families', sa.Column('timezone', sa.String(64), nullable=False, server_default='Asia/Kolkata'))

    # Populate link_code from existing join_code and membership_code with random 8-digit codes
    conn = op.get_bind()
    families = conn.execute(sa.text("SELECT id, join_code FROM families")).fetchall()
    for fam_id, jcode in families:
        lcode = jcode or _gen_code()
        mcode = _gen_code()
        conn.execute(
            sa.text("UPDATE families SET link_code = :lc, membership_code = :mc WHERE id = :fid"),
            {"lc": lcode, "mc": mcode, "fid": fam_id}
        )

    # Now alter columns to nullable=False and unique index
    op.alter_column('families', 'membership_code', nullable=False)
    op.alter_column('families', 'link_code', nullable=False)
    op.create_index('ix_families_membership_code', 'families', ['membership_code'], unique=True)
    op.create_index('ix_families_link_code', 'families', ['link_code'], unique=True)

    # 2. Create fos_family_join_requests
    op.create_table(
        'fos_family_join_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_join_requests_family_status', 'fos_family_join_requests', ['family_id', 'status'])
    op.create_index('ix_join_requests_user_status', 'fos_family_join_requests', ['user_id', 'status'])

    # 3. Create fos_family_invites
    op.create_table(
        'fos_family_invites',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('email', sa.String(320), nullable=False, index=True),
        sa.Column('token', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('fos_family_invites')
    op.drop_table('fos_family_join_requests')
    op.drop_index('ix_families_link_code', 'families')
    op.drop_index('ix_families_membership_code', 'families')
    op.drop_column('families', 'timezone')
    op.drop_column('families', 'link_code')
    op.drop_column('families', 'membership_code')
