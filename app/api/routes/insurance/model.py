from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime


class FamilyInsurance(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    insurance_name: str
    type: str # HEALTH, LIFE, TERM, VEHICLE, HOME, TRAVEL, etc
    provider: Optional[str] = Field(default=None)
    policy_number: Optional[str] = Field(default=None)
    insured_member: Optional[UUID] = Field(default=None, foreign_key="users.id") # Whose life/asset is covered
    nominee: Optional[str] = Field(default=None)

    coverage_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # Sum assured
    premium_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, HALF_YEARLY, YEARLY, ONE_TIME
    next_premium_date: Optional[datetime] = Field(default=None)
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    maturity_date: Optional[datetime] = Field(default=None)
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    status: str = Field(default="ACTIVE")  # ACTIVE, LAPSED, MATURED, CLAIMED, CANCELLED
    requires_confirmation: bool = Field(default=True)  # Plan 05
    bounce_fine_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)  # Plan 05
    allow_auto_lapse: bool = Field(default=True)  # Plan 05: auto-lapse after 2 skips
    insured_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")  # Plan 05
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )  # Plan 05

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY")  # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyInsuranceAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_insurance_access"

    insurance_id: UUID = Field(foreign_key="family_insurances.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyInsurances(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    insurance_id: UUID = Field(foreign_key="family_insurances.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalInsurance(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    user_id: UUID = Field(foreign_key="users.id")
    insurance_name: str
    type: str # HEALTH, LIFE, TERM, VEHICLE, HOME, TRAVEL, etc
    provider: Optional[str] = Field(default=None)
    policy_number: Optional[str] = Field(default=None)
    insured_member: Optional[UUID] = Field(default=None, foreign_key="users.id")
    nominee: Optional[str] = Field(default=None)

    coverage_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, HALF_YEARLY, YEARLY, ONE_TIME
    next_premium_date: Optional[datetime] = Field(default=None)
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    maturity_date: Optional[datetime] = Field(default=None)
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    status: str = Field(default="ACTIVE")  # ACTIVE, LAPSED, MATURED, CLAIMED, CANCELLED
    requires_confirmation: bool = Field(default=True)  # Plan 05
    bounce_fine_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)  # Plan 05
    allow_auto_lapse: bool = Field(default=True)  # Plan 05
    insured_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")  # Plan 05
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )  # Plan 05

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    deducted_from: Optional[str] = Field(default=None)
    access_level: str = Field(default="PRIVATE")  # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalInsuranceAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_insurance_access"

    insurance_id: UUID = Field(foreign_key="personal_insurances.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
