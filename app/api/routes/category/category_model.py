from typing import ClassVar, Optional
from datetime import datetime
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class FosCategory(SQLModel, table=True):
    """User-created category.

    FAMILY scope: one shared list per family (owner_user_id = creator).
    PERSONAL scope: private to owner_user_id.
    """

    __tablename__: ClassVar[str] = "fos_categories"
    __table_args__ = (
        Index(
            "uq_fos_categories_family_name",
            "family_id",
            "category_type",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("scope = 'FAMILY'"),
        ),
        Index(
            "uq_fos_categories_personal_name",
            "owner_user_id",
            "category_type",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("scope = 'PERSONAL'"),
        ),
    )

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    scope: str = Field(sa_column=Column(String(16), nullable=False))
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_user_id: Optional[UUID] = Field(default=None, sa_column=Column(PG_UUID(as_uuid=True), nullable=True))
    category_type: str = Field(sa_column=Column(String(32), nullable=False))
    name: str = Field(sa_column=Column(String(64), nullable=False))
    color: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    icon: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
