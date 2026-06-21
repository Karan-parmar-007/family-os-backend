from typing import ClassVar, Optional
from datetime import datetime
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime
from app.api.routes.user.model import UserBase


class RefreshToken(SQLModel, table=True):
    __tablename__: ClassVar[str] = "refresh_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    token: str = Field(nullable=False, unique=True)
    token_family_id: UUID = Field(default_factory=uuid6.uuid7)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)

    user: Optional["UserBase"] = Relationship(back_populates="refresh_tokens")


class ForgetPasswordToken(SQLModel, table=True):
    __tablename__: ClassVar[str] = "forget_password_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    token: str = Field(nullable=False, unique=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)

    user: Optional["UserBase"] = Relationship(back_populates="forget_password_tokens")


class ResetPasswordToken(SQLModel, table=True):
    __tablename__: ClassVar[str] = "reset_password_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    token: str = Field(nullable=False, unique=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)

    user: Optional["UserBase"] = Relationship(back_populates="reset_password_tokens")


class EmailVerificationToken(SQLModel, table=True):
    __tablename__: ClassVar[str] = "email_verification_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    token: str = Field(nullable=False, unique=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)

    user: Optional["UserBase"] = Relationship(back_populates="email_verification_tokens")


class EmailChangeToken(SQLModel, table=True):
    __tablename__: ClassVar[str] = "email_change_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    user_id: UUID = Field(foreign_key="users.id", nullable=False)
    new_email: str = Field(nullable=False)
    otp_hash: str = Field(nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)

    user: Optional["UserBase"] = Relationship(back_populates="email_change_tokens")



class FamilyAccountSetupToken(SQLModel, table=True):
    """Token for inviting a non-existing user to set up their family account."""
    __tablename__: ClassVar[str] = "family_account_setup_tokens"

    id: Optional[UUID] = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        nullable=False,
        unique=True,
    )
    email: str = Field(nullable=False)
    token: str = Field(nullable=False, unique=True)
    family_id: UUID = Field(foreign_key="families.id", nullable=False)
    invited_by: UUID = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(nullable=False)


