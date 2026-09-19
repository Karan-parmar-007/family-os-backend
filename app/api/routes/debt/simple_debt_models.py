from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, String, Boolean, Numeric, ForeignKey


class FosDebt(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_debts"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    scope: str = Field(sa_column=Column(String(16), nullable=False)) # FAMILY | PERSONAL
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_type: str = Field(default="FAMILY", sa_column=Column(String(16), nullable=False)) # MEMBER | FAMILY | SELF
    owner_user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    amount_paid: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False, server_default="0.00"))
    has_emi: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    add_emi_to_paid: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    category_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey('fos_categories.id', ondelete='SET NULL'), nullable=True))
    linked_rule_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("fos_money_rules.id", ondelete="SET NULL"), nullable=True))
    document_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True))
    let_everyone_edit: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    created_by: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    status: str = Field(default="OPEN", sa_column=Column(String(16), nullable=False, server_default="OPEN")) # OPEN | SETTLED
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
