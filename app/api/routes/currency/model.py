from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, Numeric, String, Boolean


class FosCurrency(SQLModel, table=True):
    """Currencies catalog with rate_to_usd (Phase 4)."""
    __tablename__: ClassVar[str] = "fos_currencies"

    code: str = Field(primary_key=True, max_length=3)
    name: str = Field(max_length=50)
    symbol: str = Field(max_length=10)
    rate_to_usd: Decimal = Field(
        default=Decimal("1.0"),
        sa_column=Column(Numeric(18, 8), nullable=False, server_default="1.0"),
    )
    logo_key: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class CurrencyRate(SQLModel, table=True):
    """Legacy currency pair rates table (kept for backward compatibility)."""
    __tablename__: ClassVar[str] = "currency_rates"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    base_currency: str = Field(max_length=8)
    quote_currency: str = Field(max_length=8)
    rate: Decimal = Field(default=0, max_digits=18, decimal_places=8)
    status: str = Field(default="DRAFT")
    effective_from: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    finalized_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    finalized_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
