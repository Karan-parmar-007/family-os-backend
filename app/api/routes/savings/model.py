from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime


class PersonalSavingslogs(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    ) 

class PersonalSavingsLogsAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_logs_access"

    savings_id: UUID = Field(foreign_key="personal_savings_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
