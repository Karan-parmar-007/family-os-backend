"""Default-bucket service (Family System V2 – Plan 01).

The default bucket tracks missed / bounced payments for debt/savings-plan entities.
An entity cannot transition to COMPLETED while it has OPEN entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, func

from app.core.constants import (
    DEFAULT_BUCKET_STATUS_OPEN,
    DEFAULT_BUCKET_STATUS_SETTLED,
    DEFAULT_BUCKET_STATUS_WAIVED,
    LEDGER_SOURCE_DEFAULT_SETTLEMENT,
)


# ---------------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------------


class DefaultBucketEntry(SQLModel, table=True):
    """One missed/bounced payment recorded against an entity."""

    __tablename__ = "default_bucket_entries"  # type: ignore[assignment]

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    entity_type: str
    entity_id: UUID = Field(index=True)
    # owner scope — exactly one of these is set
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    period_key: str  # which period was missed
    amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    fine_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    reason: str  # DEFAULT_BUCKET_REASON_BOUNCED | DEFAULT_BUCKET_REASON_SKIPPED_TO_DEFAULT
    status: str = Field(default=DEFAULT_BUCKET_STATUS_OPEN)  # OPEN | SETTLED | WAIVED
    settled_at: Optional[datetime] = Field(default=None)
    settle_ledger_note: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DefaultBucketService:
    """CRUD + settlement operations for the default bucket."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_entry(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        period_key: str,
        amount: Decimal,
        reason: str,
        fine_amount: Decimal = Decimal("0"),
        family_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> DefaultBucketEntry:
        entry = DefaultBucketEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            family_id=family_id,
            user_id=user_id,
            period_key=period_key,
            amount=amount,
            fine_amount=fine_amount,
            reason=reason,
            status=DEFAULT_BUCKET_STATUS_OPEN,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_open(
        self,
        entity_type: str,
        entity_id: UUID,
    ) -> list[DefaultBucketEntry]:
        stmt = select(DefaultBucketEntry).where(
            DefaultBucketEntry.entity_type == entity_type,
            DefaultBucketEntry.entity_id == entity_id,
            DefaultBucketEntry.status == DEFAULT_BUCKET_STATUS_OPEN,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def total_open(
        self,
        entity_type: str,
        entity_id: UUID,
    ) -> Decimal:
        """Return total (amount + fine_amount) for all OPEN entries."""
        entries = await self.list_open(entity_type, entity_id)
        return sum((e.amount + e.fine_amount for e in entries), Decimal("0"))

    async def settle(
        self,
        entry_id: UUID,
        *,
        split_lines: list[dict] | None = None,
        note: str | None = None,
    ) -> DefaultBucketEntry:
        """Settle an OPEN entry by debiting pools via FundingService.

        `split_lines` is a list of dicts: {pool_type, family_id?, user_id?, amount}.
        If None, caller must handle pool deduction manually.
        """
        stmt = select(DefaultBucketEntry).where(DefaultBucketEntry.id == entry_id)
        entry = (await self.session.execute(stmt)).scalar_one_or_none()
        if entry is None:
            raise ValueError(f"DefaultBucketEntry {entry_id} not found")
        if entry.status != DEFAULT_BUCKET_STATUS_OPEN:
            raise ValueError(f"Entry {entry_id} is not OPEN (status={entry.status})")

        total_to_settle = entry.amount + entry.fine_amount

        if split_lines:
            from app.core.funding_service import FundingService, SplitLine
            from decimal import Decimal as D

            svc = FundingService(self.session)
            lines = [
                SplitLine(
                    pool_type=ln["pool_type"],
                    amount=D(str(ln["amount"])),
                    family_id=ln.get("family_id"),
                    user_id=ln.get("user_id"),
                )
                for ln in split_lines
            ]
            await svc.execute_debit(
                lines,
                total_to_settle,
                ledger_source_type=LEDGER_SOURCE_DEFAULT_SETTLEMENT,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                description=note or f"Default bucket settlement for {entry.entity_type}",
            )

        now = datetime.now(timezone.utc)
        entry.status = DEFAULT_BUCKET_STATUS_SETTLED
        entry.settled_at = now
        entry.settle_ledger_note = note
        await self.session.flush()
        return entry

    async def waive(self, entry_id: UUID, *, note: str | None = None) -> DefaultBucketEntry:
        """Waive an OPEN entry without pool deduction."""
        stmt = select(DefaultBucketEntry).where(DefaultBucketEntry.id == entry_id)
        entry = (await self.session.execute(stmt)).scalar_one_or_none()
        if entry is None:
            raise ValueError(f"DefaultBucketEntry {entry_id} not found")
        if entry.status != DEFAULT_BUCKET_STATUS_OPEN:
            raise ValueError(f"Entry {entry_id} is not OPEN (status={entry.status})")
        now = datetime.now(timezone.utc)
        entry.status = DEFAULT_BUCKET_STATUS_WAIVED
        entry.settled_at = now
        entry.settle_ledger_note = note
        await self.session.flush()
        return entry
