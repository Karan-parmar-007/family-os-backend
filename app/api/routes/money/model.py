from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime, String, Boolean, Numeric, ForeignKey


class FosMoneyRule(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_money_rules"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    scope: str = Field(sa_column=Column(String(16), nullable=False)) # FAMILY | PERSONAL
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True))
    kind: str = Field(sa_column=Column(String(16), nullable=False)) # INCOME | EXPENSE
    name: str = Field(sa_column=Column(String(255), nullable=False))
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    category_id: Optional[UUID] = Field(default=None)
    frequency: str = Field(default="MONTHLY", sa_column=Column(String(32), nullable=False, server_default="MONTHLY"))
    next_run_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    document_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True))
    let_everyone_edit: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    created_by: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    insurance_id: Optional[UUID] = Field(default=None)
    debt_id: Optional[UUID] = Field(default=None)
    emi_remaining: Optional[int] = Field(default=None)
    status: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False, server_default="ACTIVE"))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))

    parties: List["FosMoneyRuleParty"] = Relationship(
        back_populates="rule",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )


class FosMoneyRuleParty(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_money_rule_parties"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    rule_id: UUID = Field(sa_column=Column(ForeignKey("fos_money_rules.id", ondelete="CASCADE"), nullable=False, index=True))
    party_type: str = Field(sa_column=Column(String(16), nullable=False)) # MEMBER | FAMILY
    user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    rule: Optional[FosMoneyRule] = Relationship(back_populates="parties")


class FosMoneyEvent(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_money_events"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    rule_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("fos_money_rules.id", ondelete="SET NULL"), nullable=True, index=True))
    scope: str = Field(sa_column=Column(String(16), nullable=False))
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True))
    kind: str = Field(sa_column=Column(String(16), nullable=False)) # INCOME | EXPENSE
    name: str = Field(sa_column=Column(String(255), nullable=False))
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    category_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True))
    let_everyone_edit: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    occurred_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_by: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    parties: List["FosMoneyEventParty"] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )


class FosMoneyEventParty(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_money_event_parties"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    event_id: UUID = Field(sa_column=Column(ForeignKey("fos_money_events.id", ondelete="CASCADE"), nullable=False, index=True))
    party_type: str = Field(sa_column=Column(String(16), nullable=False)) # MEMBER | FAMILY
    user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    event: Optional[FosMoneyEvent] = Relationship(back_populates="parties")
