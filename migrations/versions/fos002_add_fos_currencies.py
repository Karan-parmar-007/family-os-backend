"""add fos_currencies table and seed base currencies

Revision ID: fos002_currencies
Revises: fos001_profiles
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision = 'fos002_currencies'
down_revision = 'fos001_profiles'
branch_labels = None
depends_on = None


def upgrade() -> None:
    currencies_table = op.create_table(
        'fos_currencies',
        sa.Column('code', sa.String(3), nullable=False, primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('symbol', sa.String(10), nullable=False),
        sa.Column('rate_to_usd', sa.Numeric(18, 8), nullable=False, server_default='1.0'),
        sa.Column('logo_key', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Seed core currencies
    op.bulk_insert(
        currencies_table,
        [
            {"code": "USD", "name": "US Dollar", "symbol": "$", "rate_to_usd": 1.0, "is_active": True},
            {"code": "INR", "name": "Indian Rupee", "symbol": "₹", "rate_to_usd": 0.012, "is_active": True},
            {"code": "EUR", "name": "Euro", "symbol": "€", "rate_to_usd": 1.08, "is_active": True},
            {"code": "GBP", "name": "British Pound", "symbol": "£", "rate_to_usd": 1.27, "is_active": True},
            {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ", "rate_to_usd": 0.272, "is_active": True},
            {"code": "SGD", "name": "Singapore Dollar", "symbol": "S$", "rate_to_usd": 0.76, "is_active": True},
            {"code": "JPY", "name": "Japanese Yen", "symbol": "¥", "rate_to_usd": 0.0067, "is_active": True},
            {"code": "AUD", "name": "Australian Dollar", "symbol": "A$", "rate_to_usd": 0.65, "is_active": True},
            {"code": "CAD", "name": "Canadian Dollar", "symbol": "C$", "rate_to_usd": 0.73, "is_active": True},
        ]
    )


def downgrade() -> None:
    op.drop_table('fos_currencies')
