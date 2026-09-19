from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel, func


class Transfer(SQLModel, table=True):
    __tablename__: ClassVar[str] = "transfers"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    # Nullable for pure PERSONAL↔PERSONAL transfers.
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    to_family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    from_scope: str
    from_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    to_scope: str
    to_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    entity_type: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    source_entity_id: Optional[UUID] = Field(default=None)
    total_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    remaining_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    transfer_logs: bool = Field(default=False)
    transfer_docs: bool = Field(default=False)
    is_recurring: bool = Field(default=False)
    recurring_every: Optional[str] = Field(default=None)
    next_run_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    end_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )  # Plan 08
    requires_confirmation: bool = Field(default=True)  # Plan 08
    show_breakdown_to_receiver: bool = Field(default=True)  # Plan 08
    note: Optional[str] = Field(default=None)  # Plan 08
    status: str = Field(default="PENDING")
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_by: UUID = Field(foreign_key="users.id")
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
