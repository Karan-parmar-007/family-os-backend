from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime
from app.api.routes.user.model import UserBase, UserFamilyLink


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

