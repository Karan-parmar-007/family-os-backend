from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime


class FamilySavingsPlan(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    plan_name: str
    purpose_type: str = Field(default="GENERAL") # GENERAL, INSURANCE, EXPENSE, ASSET, INVESTMENT, DEBT
    linked_type: Optional[str] = Field(default=None) # e.g. FAMILY_INSURANCE, FAMILY_EXPENSE, FAMILY_ASSET, FAMILY_DEBT
    linked_id: Optional[UUID] = Field(default=None) # UUID of the linked record

    # The real bill we are saving toward
    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # e.g. 50k
    accumulated_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # Saved so far
    target_frequency: Optional[str] = Field(default=None) # How often the bill recurs: YEARLY, HALF_YEARLY, QUARTERLY
    next_target_date: Optional[datetime] = Field(default=None) # When the bill is next due

    # How we set money aside for it
    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2) # e.g. 3k
    contribution_every: str = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=True) # Auto-accrue contribution on schedule
    deduct_at_period_start: bool = Field(default=True) # Deduct at start of the period
    # Sinking-fund / EMI behavior
    confirm_contributions: bool = Field(default=False) # Ask before each contribution (notification)
    requires_confirmation: bool = Field(default=False)  # Plan 06: replaces confirm_contributions
    emi_mode: str = Field(default="FIXED") # FIXED, AUTO_RECOMPUTE
    funded_from: Optional[str] = Field(default=None) # e.g. "FAMILY_INCOME"
    skip_fine_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)  # Plan 06
    status: str = Field(default="ACTIVE") # ACTIVE, PAUSED, COMPLETED, CANCELLED
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )  # Plan 06

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilySavingsPlanAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plan_access"

    plan_id: UUID = Field(foreign_key="family_savings_plans.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilySavingsPlans(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    plan_id: UUID = Field(foreign_key="family_savings_plans.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilySavingsPlanContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plan_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    plan_id: UUID = Field(foreign_key="family_savings_plans.id", index=True)
    contributed_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (accrual), OUT (bill paid from fund)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlan(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    user_id: UUID = Field(foreign_key="users.id")
    plan_name: str
    purpose_type: str = Field(default="GENERAL") # GENERAL, INSURANCE, EXPENSE, ASSET, INVESTMENT, DEBT
    linked_type: Optional[str] = Field(default=None) # e.g. PERSONAL_INSURANCE, PERSONAL_EXPENSE, PERSONAL_ASSET
    linked_id: Optional[UUID] = Field(default=None)

    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    accumulated_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    target_frequency: Optional[str] = Field(default=None) # YEARLY, HALF_YEARLY, QUARTERLY
    next_target_date: Optional[datetime] = Field(default=None)

    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    contribution_every: str = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=True)
    deduct_at_period_start: bool = Field(default=True)
    # Sinking-fund / EMI behavior
    confirm_contributions: bool = Field(default=False) # Ask before each contribution (notification)
    requires_confirmation: bool = Field(default=False)  # Plan 06
    emi_mode: str = Field(default="FIXED") # FIXED, AUTO_RECOMPUTE
    funded_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    skip_fine_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)  # Plan 06
    status: str = Field(default="ACTIVE") # ACTIVE, PAUSED, COMPLETED, CANCELLED
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )  # Plan 06

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlanAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plan_access"

    plan_id: UUID = Field(foreign_key="personal_savings_plans.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlanContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plan_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    plan_id: UUID = Field(foreign_key="personal_savings_plans.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (accrual), OUT (bill paid from fund)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
