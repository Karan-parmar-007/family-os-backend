from typing import ClassVar, Optional
from datetime import datetime
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, String, Boolean, Text, ForeignKey


class FosVaultItem(SQLModel, table=True):
    __tablename__: ClassVar[str] = "fos_vault_items"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    scope: str = Field(sa_column=Column(String(16), nullable=False)) # FAMILY | PERSONAL
    family_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True))
    owner_user_id: UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
    kind: str = Field(sa_column=Column(String(16), nullable=False)) # PASSWORD | FILE
    title: str = Field(sa_column=Column(String(255), nullable=False))
    category: str = Field(sa_column=Column(String(64), nullable=False))
    for_party_type: str = Field(sa_column=Column(String(16), nullable=False)) # MEMBER | FAMILY | SELF
    for_user_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
    document_id: Optional[UUID] = Field(default=None, sa_column=Column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True))
    is_protected: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    ciphertext: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    nonce: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    file_key: Optional[str] = Field(default=None, sa_column=Column(String(512), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
