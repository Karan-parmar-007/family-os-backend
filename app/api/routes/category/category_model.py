from typing import ClassVar, Optional
from datetime import datetime
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, String, Boolean, ForeignKey


class FosCategory(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_categories"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    scope: str = Field(sa_column=Column(String(16), nullable=False)) # FAMILY | PERSONAL
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True))
    category_type: str = Field(sa_column=Column(String(32), nullable=False, index=True)) # INCOME | EXPENSE | DEBT | ASSET | VAULT_PASSWORD | VAULT_DOCUMENT
    name: str = Field(sa_column=Column(String(64), nullable=False))
    color: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    icon: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    is_default: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
