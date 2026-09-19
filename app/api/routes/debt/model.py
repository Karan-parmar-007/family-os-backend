"""Debt models – Family System V2 (Plan 02 rework)."""

from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, JSON


class Debt(SQLModel, table=True):
    """Canonical loan — single financial source of truth."""

    __tablename__: ClassVar[str] = "debts"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    owner_user_id: UUID = Field(foreign_key="users.id", index=True)
    primary_family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)

    debt_name: str
    type: str
    status: str = Field(default="ACTIVE", index=True)

    total_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    remaining_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    total_paid: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    balance_for_part_payment: Decimal = Field(default=0, max_digits=12, decimal_places=2)

    has_interest: bool = Field(default=False)
    interest_type: Optional[str] = Field(default=None)
    interest_rate: Optional[float] = Field(default=None)
    compounding_frequency: Optional[str] = Field(default=None)
    fixed_fee_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    interest_increase_every: Optional[str] = Field(default=None)
    interest_increase_percentage: Optional[float] = Field(default=None)
    next_interest_increase_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    has_emi: bool = Field(default=False)
    emi_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    emi_every: Optional[str] = Field(default="MONTHLY")
    # Custom EMI interval (alternative to emi_every preset)
    emi_interval_days: Optional[int] = Field(default=None)
    emi_interval_months: Optional[int] = Field(default=None)
    emi_interval_years: Optional[int] = Field(default=None)
    tenure_months: Optional[int] = Field(default=None)
    emi_next_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    requires_confirmation: bool = Field(default=True)

    bounce_fine_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    allow_auto_default: bool = Field(default=True)

    start_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    end_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    show_doc_to_all: bool = Field(default=True)
    doc_viewer_user_ids: Optional[List[UUID]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class DebtScopeView(SQLModel, table=True):
    """Per-scope display of a canonical debt (personal or family)."""

    __tablename__: ClassVar[str] = "debt_scope_views"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    debt_id: UUID = Field(foreign_key="debts.id", index=True)
    scope_kind: str  # PERSONAL | FAMILY
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    is_primary: bool = Field(default=False)

    display_name: str
    display_type: Optional[str] = Field(default=None)
    display_total_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    display_remaining_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    display_emi_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    display_interest_rate: Optional[float] = Field(default=None)
    is_masked: bool = Field(default=False)
    show_breakdown: bool = Field(default=False)
    access_level: str = Field(default="FAMILY")
    excluded: bool = Field(default=False)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class DebtPaymentEvent(SQLModel, table=True):
    __tablename__: ClassVar[str] = "debt_payment_events"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    debt_id: UUID = Field(foreign_key="debts.id", index=True)
    event_type: str  # EMI | PART_PAYMENT | ADJUSTMENT
    period_key: Optional[str] = Field(default=None)
    scheduled_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    actual_amount: Decimal = Field(max_digits=12, decimal_places=2)
    principal_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    interest_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    fee_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    paid_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    status: str = Field(default="FINALIZED")
    paid_externally: bool = Field(default=False)
    note: Optional[str] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    job_id: Optional[UUID] = Field(default=None)
    part_payment_mode: Optional[str] = Field(default=None)
    underpayment_policy: Optional[str] = Field(default=None)
    overpayment_policy: Optional[str] = Field(default=None)
    created_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class DebtPaymentAllocation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "debt_payment_allocations"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    payment_event_id: UUID = Field(foreign_key="debt_payment_events.id", index=True)
    pool_type: str
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id")
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
