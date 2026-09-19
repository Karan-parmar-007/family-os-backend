"""Multi-pool payment split service (Family System V2 – Plan 01).

Rules:
- Each debit executes atomically: either all pool movements commit or none.
- Never partially debit a split.
- Writes one SavingsLedger row + one expense log per pool in the split.
- Also writes a FundingBreakdownEntry per pool for historical attribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, func

from app.core.constants import (
    LEDGER_OUT,
    LEDGER_IN,
    LEDGER_SOURCE_DEBT_EMI,
    POOL_FAMILY,
    POOL_PERSONAL,
    SPLIT_POOL_CURRENT_FAMILY,
    SPLIT_POOL_OTHER_FAMILY,
    SPLIT_POOL_PERSONAL,
    FUNDING_EXTERNAL,
)
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class PaymentSplitPlan(SQLModel, table=True):
    """Stored split configuration attached to a recurring entity."""

    __tablename__ = "payment_split_plans"  # type: ignore[assignment]

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    entity_type: str  # e.g. ENTITY_FAMILY_DEBT
    entity_id: UUID
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class PaymentSplitLine(SQLModel, table=True):
    """One funding-pool line within a split plan."""

    __tablename__ = "payment_split_lines"  # type: ignore[assignment]

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    plan_id: UUID = Field(foreign_key="payment_split_plans.id", index=True)
    pool_type: str  # CURRENT_FAMILY | PERSONAL | OTHER_FAMILY
    # For CURRENT_FAMILY / OTHER_FAMILY pools, store the family id.
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id")
    # For PERSONAL pools, store the user whose personal savings are used.
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    # Debt multi-payer: total expected from this payer and how much still owed.
    expected_total: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    obligation_remaining: Optional[Decimal] = Field(
        default=None, max_digits=12, decimal_places=2
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class FundingBreakdownEntry(SQLModel, table=True):
    """Immutable record: which pool paid how much for a specific job/log."""

    __tablename__ = "funding_breakdown_entries"  # type: ignore[assignment]

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    entity_type: str
    entity_id: UUID = Field(index=True)
    # job_id links back to the scheduled_jobs row that triggered this payment
    job_id: Optional[UUID] = Field(default=None, foreign_key="scheduled_jobs.id", index=True)
    pool_type: str  # CURRENT_FAMILY | PERSONAL | OTHER_FAMILY | EXTERNAL
    family_id: Optional[UUID] = Field(default=None, foreign_key="families.id")
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    direction: str = Field(default=LEDGER_OUT)  # OUT for payments, IN for credits
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InsufficientFundsError(Exception):
    """Raised when a pool has less than the required amount."""

    def __init__(self, pool_type: str, family_id: UUID | None, available: Decimal, required: Decimal):
        self.pool_type = pool_type
        self.family_id = family_id
        self.available = available
        self.required = required
        super().__init__(
            f"Insufficient funds in pool {pool_type}"
            + (f" (family={family_id})" if family_id else "")
            + f": available={available}, required={required}"
        )


class SplitValidationError(Exception):
    """Raised when split lines are invalid (e.g. sum mismatch)."""


# ---------------------------------------------------------------------------
# Dataclasses for ad-hoc splits (used at call sites)
# ---------------------------------------------------------------------------


@dataclass
class SplitLine:
    """One pool contribution in an ad-hoc split."""

    pool_type: str           # SPLIT_POOL_CURRENT_FAMILY | SPLIT_POOL_PERSONAL | SPLIT_POOL_OTHER_FAMILY
    amount: Decimal
    family_id: Optional[UUID] = None   # required for CURRENT_FAMILY / OTHER_FAMILY
    user_id: Optional[UUID] = None     # required for PERSONAL

    def to_pool_ref(self) -> SavingsPoolRef:
        if self.pool_type in (SPLIT_POOL_CURRENT_FAMILY, SPLIT_POOL_OTHER_FAMILY):
            return SavingsPoolRef(pool_type=POOL_FAMILY, family_id=self.family_id)
        return SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=self.user_id)


# ---------------------------------------------------------------------------
# FundingService
# ---------------------------------------------------------------------------


class FundingService:
    """Orchestrates multi-pool payments with atomic debit + breakdown records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._ledger = SavingsLedgerService(session)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_split(lines: list[SplitLine], expected_total: Decimal) -> None:
        """Raise SplitValidationError if lines don't sum to expected_total."""
        errors: list[str] = []
        total = sum(ln.amount for ln in lines)
        if abs(total - expected_total) > Decimal("0.01"):
            errors.append(
                f"Split lines sum to {total} but expected_total is {expected_total}"
            )
        for i, ln in enumerate(lines):
            if ln.amount <= 0:
                errors.append(f"Line {i}: amount must be positive, got {ln.amount}")
            if ln.pool_type in (SPLIT_POOL_CURRENT_FAMILY, SPLIT_POOL_OTHER_FAMILY) and not ln.family_id:
                errors.append(f"Line {i}: family_id required for pool_type={ln.pool_type}")
            if ln.pool_type == SPLIT_POOL_PERSONAL and not ln.user_id:
                errors.append(f"Line {i}: user_id required for pool_type={ln.pool_type}")
        if errors:
            raise SplitValidationError("; ".join(errors))

    # ------------------------------------------------------------------
    # Debit helpers
    # ------------------------------------------------------------------

    async def _check_sufficient_funds(self, pool_ref: SavingsPoolRef, amount: Decimal) -> None:
        """Raise InsufficientFundsError if pool has less than `amount`."""
        from app.api.routes.family.model import FamilyTotalSavings, UserGlobalPersonalSavings

        if pool_ref.pool_type == POOL_FAMILY:
            stmt = select(FamilyTotalSavings).where(
                FamilyTotalSavings.family_id == pool_ref.family_id
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            available = row.total_savings if row else Decimal("0")
        else:
            stmt = select(UserGlobalPersonalSavings).where(
                UserGlobalPersonalSavings.user_id == pool_ref.user_id
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            available = row.total_savings if row else Decimal("0")

        if available < amount:
            raise InsufficientFundsError(
                pool_ref.pool_type, pool_ref.family_id, available, amount
            )

    async def execute_debit(
        self,
        lines: list[SplitLine],
        total: Decimal,
        *,
        ledger_source_type: str,
        entity_type: str,
        entity_id: UUID,
        job_id: Optional[UUID] = None,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> list[FundingBreakdownEntry]:
        """Atomic multi-pool debit. Writes ledger rows + breakdown entries.

        Raises InsufficientFundsError (rolls back nothing — caller must handle).
        Validates lines first so no pool is touched if validation fails.
        """
        self.validate_split(lines, total)
        when = occurred_at or datetime.now(timezone.utc)

        # Pre-check all pools BEFORE touching any (atomicity guarantee)
        for ln in lines:
            pool_ref = ln.to_pool_ref()
            await self._check_sufficient_funds(pool_ref, ln.amount)

        breakdown_entries: list[FundingBreakdownEntry] = []
        for ln in lines:
            pool_ref = ln.to_pool_ref()
            await self._ledger.apply_movement(
                pool_ref,
                ln.amount,
                LEDGER_OUT,
                ledger_source_type,
                source_id=entity_id,
                description=description,
                occurred_at=when,
            )
            entry = FundingBreakdownEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                job_id=job_id,
                pool_type=ln.pool_type,
                family_id=ln.family_id,
                user_id=ln.user_id,
                amount=ln.amount,
                direction=LEDGER_OUT,
            )
            self.session.add(entry)
            breakdown_entries.append(entry)

        await self.session.flush()
        return breakdown_entries

    async def execute_debit_adhoc(
        self,
        pool_ref: SavingsPoolRef,
        amount: Decimal,
        *,
        ledger_source_type: str,
        entity_type: str,
        entity_id: UUID,
        job_id: Optional[UUID] = None,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> FundingBreakdownEntry:
        """Single-pool ad-hoc debit (e.g. default bucket settlement)."""
        when = occurred_at or datetime.now(timezone.utc)
        await self._check_sufficient_funds(pool_ref, amount)
        await self._ledger.apply_movement(
            pool_ref,
            amount,
            LEDGER_OUT,
            ledger_source_type,
            source_id=entity_id,
            description=description,
            occurred_at=when,
        )
        pool_type = SPLIT_POOL_CURRENT_FAMILY if pool_ref.pool_type == POOL_FAMILY else SPLIT_POOL_PERSONAL
        entry = FundingBreakdownEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            job_id=job_id,
            pool_type=pool_type,
            family_id=pool_ref.family_id,
            user_id=pool_ref.user_id,
            amount=amount,
            direction=LEDGER_OUT,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def execute_paid_externally(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        amount: Decimal,
        job_id: Optional[UUID] = None,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> FundingBreakdownEntry:
        """Record a payment as PAID_EXTERNALLY — no pool deduction, just a breakdown entry."""
        when = occurred_at or datetime.now(timezone.utc)
        entry = FundingBreakdownEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            job_id=job_id,
            pool_type=FUNDING_EXTERNAL,
            family_id=None,
            user_id=None,
            amount=amount,
            direction=LEDGER_OUT,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def _get_or_create_split_plan(
        self, entity_type: str, entity_id: UUID, *, create: bool = False
    ) -> PaymentSplitPlan | None:
        """Return the canonical plan for (entity_type, entity_id).

        Legacy dual-write left duplicate DEBT plans; keep the newest and drop extras
        when writing. Reads pick the newest without mutating.
        """
        from sqlalchemy import delete

        plan_stmt = (
            select(PaymentSplitPlan)
            .where(
                PaymentSplitPlan.entity_type == entity_type,
                PaymentSplitPlan.entity_id == entity_id,
            )
            .order_by(PaymentSplitPlan.created_at.desc(), PaymentSplitPlan.id.desc())
        )
        plans = list((await self.session.execute(plan_stmt)).scalars().all())
        if not plans:
            if not create:
                return None
            plan = PaymentSplitPlan(entity_type=entity_type, entity_id=entity_id)
            self.session.add(plan)
            await self.session.flush()
            return plan

        plan = plans[0]
        if create and len(plans) > 1:
            extra_ids = [p.id for p in plans[1:]]
            await self.session.execute(
                delete(PaymentSplitLine).where(PaymentSplitLine.plan_id.in_(extra_ids))
            )
            await self.session.execute(
                delete(PaymentSplitPlan).where(PaymentSplitPlan.id.in_(extra_ids))
            )
            await self.session.flush()
        return plan

    async def load_split_plan(
        self, entity_type: str, entity_id: UUID
    ) -> list[PaymentSplitLine] | None:
        """Return stored split lines for an entity, or None if none configured."""
        plan = await self._get_or_create_split_plan(entity_type, entity_id)
        if plan is None:
            return None
        lines_stmt = select(PaymentSplitLine).where(PaymentSplitLine.plan_id == plan.id)
        return list((await self.session.execute(lines_stmt)).scalars().all())

    async def save_split_plan(
        self,
        entity_type: str,
        entity_id: UUID,
        lines: list[dict],
    ) -> PaymentSplitPlan:
        """Upsert a split plan for an entity. `lines` is list of dicts with pool_type/family_id/user_id/amount."""
        from sqlalchemy import delete

        plan = await self._get_or_create_split_plan(
            entity_type, entity_id, create=True
        )
        assert plan is not None

        # Delete existing lines and recreate
        await self.session.execute(
            delete(PaymentSplitLine).where(PaymentSplitLine.plan_id == plan.id)
        )
        for ln in lines:
            expected = ln.get("expected_total")
            obligation = ln.get("obligation_remaining")
            if obligation is None and expected is not None:
                obligation = expected
            self.session.add(
                PaymentSplitLine(
                    plan_id=plan.id,
                    pool_type=ln["pool_type"],
                    family_id=ln.get("family_id"),
                    user_id=ln.get("user_id"),
                    amount=Decimal(str(ln["amount"])),
                    expected_total=(
                        Decimal(str(expected)) if expected is not None else None
                    ),
                    obligation_remaining=(
                        Decimal(str(obligation)) if obligation is not None else None
                    ),
                )
            )
        await self.session.flush()
        return plan
