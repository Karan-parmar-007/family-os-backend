import secrets
from datetime import datetime
from typing import ClassVar, List, TYPE_CHECKING
from uuid import UUID

import uuid6
from pydantic import EmailStr
from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, Relationship, SQLModel, func

if TYPE_CHECKING:
    from app.api.routes.family.model import Family


def generate_friend_code() -> str:
    """Generate an 8-digit numeric friend code (keeps leading zeros)."""
    return f"{secrets.randbelow(100000000):08d}"


class UserFamilyLink(SQLModel, table=True):
    __tablename__: ClassVar[str] = "user_family_links"

    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", primary_key=True)
    is_family_manager: bool = Field(default=False)
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


class UserBase(SQLModel, table=True):
    __tablename__: ClassVar[str] = "users"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    email: EmailStr = Field(index=True, unique=True)
    name: str
    password: str
    is_active: bool = Field(default=True)
    is_premium_user: bool = Field(default=False)
    is_email_verified: bool = Field(default=False)
    is_super_admin: bool = Field(default=False)  # Plan 10
    preferred_currency: str = Field(default="INR")  # Plan 10
    personal_currency: str = Field(default="INR")  # Plan 10
    friend_code: str = Field(
        default_factory=generate_friend_code,
        sa_column=Column(String(length=8), unique=True, index=True, nullable=False),
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

    families: List["Family"] = Relationship(
        back_populates="users",
        link_model=UserFamilyLink,
    )


