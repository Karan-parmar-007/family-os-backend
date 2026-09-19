from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Dict, Optional
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, func


class ScheduledJob(SQLModel, table=True):
    __tablename__: ClassVar[str] = "scheduled_jobs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    job_type: str
    source_type: str
    source_id: UUID
    assigned_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str
    period_key: str
    scheduled_for: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    requires_confirmation: bool = Field(default=False)
    status: str = Field(default="SCHEDULED")
    attempt_count: int = Field(default=0)
    delay_days: int = Field(default=0)
    next_retry_at: Optional[datetime] = Field(default=None)
    awaiting_since: Optional[datetime] = Field(default=None)
    applied_ledger_id: Optional[UUID] = Field(default=None)
    notification_id: Optional[UUID] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    # Stores reschedule metadata, e.g. {"original_next_date": "2026-07-01"} for ONE_TIME mode
    meta: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSONB, nullable=True))
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


class Notification(SQLModel, table=True):
    __tablename__: ClassVar[str] = "notifications"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id")
    type: str
    title: str
    body: Optional[str] = Field(default=None)
    related_job_id: Optional[UUID] = Field(default=None, foreign_key="scheduled_jobs.id")
    related_entity_type: Optional[str] = Field(default=None)
    related_entity_id: Optional[UUID] = Field(default=None)
    allowed_actions: Any = Field(sa_column=Column(JSONB, nullable=False))
    meta: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    status: str = Field(default="UNREAD")
    action_taken: Optional[str] = Field(default=None)
    actioned_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
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


class BouncedPayment(SQLModel, table=True):
    __tablename__: ClassVar[str] = "bounced_payments"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    debt_id: UUID
    debt_scope: str
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    period_key: str
    due_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    status: str = Field(default="BOUNCED")
    job_id: Optional[UUID] = Field(default=None, foreign_key="scheduled_jobs.id")
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
