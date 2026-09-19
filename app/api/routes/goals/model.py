"""Goals model — simplified (Plan 07: no scheduled contributions, manual-only)."""
from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, Text


class FamilyGoal(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    goal_name: str
    goal_type: Optional[str] = Field(default=None)  # PROPERTY, VEHICLE, EDUCATION, TRAVEL, EMERGENCY, GENERAL
    target_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    collected_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="ACTIVE")  # ACTIVE, ACHIEVED, CANCELLED
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY")  # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyGoalAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goal_access"

    goal_id: UUID = Field(foreign_key="family_goals.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ")  # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyGoals(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    goal_id: UUID = Field(foreign_key="family_goals.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyGoalContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goal_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    goal_id: UUID = Field(foreign_key="family_goals.id", index=True)
    contributed_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN")  # IN (saved toward goal), OUT (withdrawn)
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL")  # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoal(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="PERSONAL")

    user_id: UUID = Field(foreign_key="users.id")
    goal_name: str
    goal_type: Optional[str] = Field(default=None)  # PROPERTY, VEHICLE, EDUCATION, TRAVEL, EMERGENCY, GENERAL
    target_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    collected_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="ACTIVE")  # ACTIVE, ACHIEVED, CANCELLED
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE")  # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoalAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goal_access"

    goal_id: UUID = Field(foreign_key="personal_goals.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ")  # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoalContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goal_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="PERSONAL")

    goal_id: UUID = Field(foreign_key="personal_goals.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN")  # IN (saved toward goal), OUT (withdrawn)
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL")  # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
