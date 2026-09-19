from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime


class Document(SQLModel, table=True):
    __tablename__: ClassVar[str] = "documents"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    filename: Optional[str] = Field(default=None)
    file_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
