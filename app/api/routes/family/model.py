import secrets
from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime, String, ForeignKey, Text
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.api.routes.document.model import Document


def generate_code() -> str:
    """Generate an 8-digit numeric code (keeps leading zeros)."""
    return f"{secrets.randbelow(100000000):08d}"


generate_join_code = generate_code


class Family(SQLModel, table=True):
    __tablename__: ClassVar[str] = "families"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str
    currency: str = Field(default="USD")
    timezone: str = Field(
        default="Asia/Kolkata",
        sa_column=Column(String(64), nullable=False, server_default="Asia/Kolkata"),
    )
    # membership_code: used by people to request joining this family
    membership_code: str = Field(
        default_factory=generate_code,
        sa_column=Column(String(8), unique=True, index=True, nullable=False),
    )
    # link_code: used to connect two families for cross-family transfers
    link_code: str = Field(
        default_factory=generate_code,
        sa_column=Column(String(8), unique=True, index=True, nullable=False),
    )
    # legacy join_code kept for backward compatibility
    join_code: Optional[str] = Field(
        default=None,
        sa_column=Column(String(8), unique=True, index=True, nullable=True),
    )
    vault_password_hash: Optional[str] = Field(
        default=None,
        sa_column=Column(Text(), nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

    users: List[UserBase] = Relationship(
        back_populates="families",
        link_model=UserFamilyLink,
    )


class FosFamilyJoinRequest(SQLModel, table=True):
    """Join requests submitted by members using the family membership_code."""
    __tablename__: ClassVar[str] = "fos_family_join_requests"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True))
    user_id: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
    status: str = Field(default="PENDING", sa_column=Column(String(16), nullable=False, server_default="PENDING"))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))


class FosFamilyInvite(SQLModel, table=True):
    """Email invites issued by family heads."""
    __tablename__: ClassVar[str] = "fos_family_invites"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True))
    email: str = Field(sa_column=Column(String(320), nullable=False, index=True))
    token: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    invited_by: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    status: str = Field(default="PENDING", sa_column=Column(String(16), nullable=False, server_default="PENDING"))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class FamilyTotalSavings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_total_savings"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", unique=True)
    origin_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    total_savings: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class PersonalTotalSavings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_total_savings"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id")
    user_id: UUID = Field(foreign_key="users.id")
    total_savings: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
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


class UserGlobalPersonalSavings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "user_global_personal_savings"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", unique=True)
    origin_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    total_savings: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
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


class SavingsLedger(SQLModel, table=True):
    __tablename__: ClassVar[str] = "savings_ledger"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    pool_type: str = Field(max_length=16)
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    direction: str = Field(max_length=8)
    source_type: str = Field(max_length=32)
    source_id: Optional[UUID] = Field(default=None)
    description: Optional[str] = Field(default=None, max_length=255)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class FamilyRelationship(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_relationships"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_a_id: UUID = Field(foreign_key="families.id", index=True)
    family_b_id: UUID = Field(foreign_key="families.id", index=True)
    relationship_type: Optional[str] = Field(default=None)
    label: Optional[str] = Field(default=None)
    status: str = Field(default="PENDING")
    initiated_by_family_id: UUID = Field(foreign_key="families.id")
    initiated_by_user_id: UUID = Field(foreign_key="users.id")
    responded_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class LogFundingSource(SQLModel, table=True):
    __tablename__: ClassVar[str] = "log_funding_sources"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    entity_type: str = Field(max_length=64)
    entity_id: UUID = Field(index=True)
    direction: str = Field(max_length=8)
    pool_type: str = Field(max_length=16)
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
