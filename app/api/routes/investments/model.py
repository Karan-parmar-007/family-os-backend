"""Investment models (Family System V2 – Plan 04).

FamilyInvestment / PersonalInvestment + InvestmentTxn + access/exclude tables.
"""

from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime


class FamilyInvestment(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_investments"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    investment_name: str
    type: str   # INVESTMENT_TYPES in investment_schemas.py
    status: str = Field(default="ACTIVE")  # ACTIVE | MATURED | CLOSED | CANCELLED

    in_someone_name: Optional[UUID] = Field(default=None, foreign_key="users.id")

    # Financials
    invested_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    current_value: Decimal = Field(default=0, max_digits=12, decimal_places=2)

    # Returns
    return_type: Optional[str] = Field(default=None)  # SIMPLE | COMPOUND | MARKET
    annual_return_rate: Optional[float] = Field(default=None)
    compounding_frequency: Optional[str] = Field(default=None)  # for COMPOUND

    # Recurring contribution
    has_recurring: bool = Field(default=False)
    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    contribution_every: Optional[str] = Field(default=None)
    next_contribution_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    tenure_months: Optional[int] = Field(default=None)
    requires_confirmation: bool = Field(default=True)

    # Maturity
    maturity_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    auto_credit_on_maturity: bool = Field(default=True)

    # Completion
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class FamilyInvestmentAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_investment_access"

    investment_id: UUID = Field(foreign_key="family_investments.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class ExcludeFromFamilyInvestments(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_investments"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    investment_id: UUID = Field(foreign_key="family_investments.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class PersonalInvestment(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_investments"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    scope_type: str = Field(default="PERSONAL")

    investment_name: str
    type: str
    status: str = Field(default="ACTIVE")

    # Financials
    invested_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    current_value: Decimal = Field(default=0, max_digits=12, decimal_places=2)

    # Returns
    return_type: Optional[str] = Field(default=None)
    annual_return_rate: Optional[float] = Field(default=None)
    compounding_frequency: Optional[str] = Field(default=None)

    # Recurring contribution
    has_recurring: bool = Field(default=False)
    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    contribution_every: Optional[str] = Field(default=None)
    next_contribution_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    tenure_months: Optional[int] = Field(default=None)
    requires_confirmation: bool = Field(default=True)

    # Maturity
    maturity_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    auto_credit_on_maturity: bool = Field(default=True)

    # Completion
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class PersonalInvestmentAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_investment_access"

    investment_id: UUID = Field(foreign_key="personal_investments.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class InvestmentTxn(SQLModel, table=True):
    """Every money-in/out on an investment."""

    __tablename__: ClassVar[str] = "investment_txns"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    investment_scope: str       # FAMILY | PERSONAL
    investment_id: UUID = Field(index=True)
    txn_type: str               # CONTRIBUTION | LUMP_SUM | REDEMPTION | MATURITY_CREDIT | VALUE_ADJUST
    amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN")  # IN | OUT
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL")  # MANUAL | SCHEDULED
    job_id: Optional[UUID] = Field(default=None, foreign_key="scheduled_jobs.id")
    note: Optional[str] = Field(default=None)
    created_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
