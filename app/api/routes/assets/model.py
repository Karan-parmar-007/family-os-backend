"""Asset models – Physical assets only (Family System V2 – Plan 03).

Assets represent physical items: home, car, gold, etc.
No EMI, no auto-increase. A loan is a separate Debt row.
"""

from typing import ClassVar, Optional
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, Date, DateTime


class FamilyAssets(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    asset_name: str
    type: str  # validated against ASSET_TYPES in assets_schemas.py
    in_someone_name: Optional[UUID] = Field(default=None, foreign_key="users.id")

    value: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    quantity: Optional[Decimal] = Field(default=1, max_digits=12, decimal_places=4)
    quantity_label: Optional[str] = Field(default=None)
    acquired_on: Optional[date] = Field(
        default=None, sa_column=Column(Date(), nullable=True)
    )
    notes: Optional[str] = Field(default=None)

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY")  # PRIVATE | FAMILY | SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class ExcludeFromFamilyAssets(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    asset_id: UUID = Field(foreign_key="family_assets.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class FamilyAssetAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_asset_access"

    asset_id: UUID = Field(foreign_key="family_assets.id", primary_key=True)
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


class PersonalAsset(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    scope_type: str = Field(default="PERSONAL")

    asset_name: str
    type: str

    value: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    quantity: Optional[Decimal] = Field(default=1, max_digits=12, decimal_places=4)
    quantity_label: Optional[str] = Field(default=None)
    acquired_on: Optional[date] = Field(
        default=None, sa_column=Column(Date(), nullable=True)
    )
    notes: Optional[str] = Field(default=None)

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE")  # PRIVATE | SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class PersonalAssetAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_asset_access"

    asset_id: UUID = Field(foreign_key="personal_assets.id", primary_key=True)
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
