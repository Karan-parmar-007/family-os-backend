# app/api/routes/profile/model.py
import secrets
from datetime import datetime
from typing import ClassVar
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, SQLModel, func


def _generate_personal_code() -> str:
    """8-digit numeric personal code (leading zeros preserved)."""
    return f"{secrets.randbelow(100_000_000):08d}"


class FosProfile(SQLModel, table=True):
    """
    One row per Family OS user, created by POST /api/familyos/me/setup.
    sso_user_id = Mongo ObjectId string from the SSO JWT 'user_id' claim.
    No password stored here — SSO owns credentials.
    """

    __tablename__: ClassVar[str] = "fos_profiles"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    sso_user_id: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True),
    )
    email: str = Field(
        sa_column=Column(String(320), unique=True, nullable=False, index=True),
    )
    display_name: str = Field(
        sa_column=Column(String(100), nullable=False),
    )
    personal_currency: str = Field(
        default="USD",
        sa_column=Column(String(3), nullable=False),
    )
    timezone: str = Field(
        default="Asia/Kolkata",
        sa_column=Column(String(64), nullable=False),
    )
    personal_code: str = Field(
        default_factory=_generate_personal_code,
        sa_column=Column(String(8), unique=True, nullable=False, index=True),
    )
    max_family_memberships: int = Field(default=2, nullable=False)
    setup_completed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    vault_password_hash: str | None = Field(
        default=None,
        sa_column=Column(Text(), nullable=True),
    )
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
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
