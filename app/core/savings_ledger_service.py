"""Ledger-backed savings operations (Family System V2)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import (
    FamilyTotalSavings,
    SavingsLedger,
    UserGlobalPersonalSavings,
)
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_MANUAL,
    LEDGER_SOURCE_ORIGIN,
    POOL_FAMILY,
    POOL_PERSONAL,
)


@dataclass(frozen=True)
class SavingsPoolRef:
    pool_type: str
    family_id: UUID | None = None
    user_id: UUID | None = None


class SavingsLedgerService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply_movement(
        self,
        pool: SavingsPoolRef,
        amount: Decimal,
        direction: str,
        source_type: str,
        *,
        source_id: UUID | None = None,
        description: str | None = None,
        document_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> SavingsLedger:
        if amount <= 0:
            raise ValueError("amount must be positive")
        if direction not in (LEDGER_IN, LEDGER_OUT):
            raise ValueError("direction must be IN or OUT")

        when = occurred_at or datetime.now(timezone.utc)
        entry = SavingsLedger(
            pool_type=pool.pool_type,
            family_id=pool.family_id,
            user_id=pool.user_id,
            amount=amount,
            direction=direction,
            source_type=source_type,
            source_id=source_id,
            description=description,
            document_id=document_id,
            occurred_at=when,
        )
        self.session.add(entry)
        await self.session.flush()

        delta = amount if direction == LEDGER_IN else -amount
        await self._update_cache(pool, delta)
        return entry

    async def set_origin(
        self,
        pool: SavingsPoolRef,
        origin_amount: Decimal,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        if origin_amount < 0:
            raise ValueError("origin_amount cannot be negative")

        row = await self._get_or_create_pool_row(pool)
        if getattr(row, "origin_amount", Decimal("0")) > 0:
            raise ValueError("Origin already set for this pool")

        row.origin_amount = origin_amount
        row.total_savings = origin_amount
        await self.session.flush()

        if origin_amount > 0:
            when = occurred_at or datetime.now(timezone.utc)
            self.session.add(
                SavingsLedger(
                    pool_type=pool.pool_type,
                    family_id=pool.family_id,
                    user_id=pool.user_id,
                    amount=origin_amount,
                    direction=LEDGER_IN,
                    source_type=LEDGER_SOURCE_ORIGIN,
                    occurred_at=when,
                )
            )
            await self.session.flush()

    async def adjust(
        self,
        pool: SavingsPoolRef,
        amount: Decimal,
        *,
        description: str | None = None,
    ) -> SavingsLedger:
        raise ValueError("Manual savings adjustments are disabled")

    async def _update_cache(self, pool: SavingsPoolRef, delta: Decimal) -> None:
        row = await self._get_or_create_pool_row(pool)
        row.total_savings = row.total_savings + delta
        await self.session.flush()

    async def _get_or_create_pool_row(
        self, pool: SavingsPoolRef
    ) -> FamilyTotalSavings | UserGlobalPersonalSavings:
        if pool.pool_type == POOL_FAMILY:
            if not pool.family_id:
                raise ValueError("family_id required for FAMILY pool")
            stmt = select(FamilyTotalSavings).where(FamilyTotalSavings.family_id == pool.family_id)
            result = await self.session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                row = FamilyTotalSavings(family_id=pool.family_id, total_savings=Decimal("0"))
                self.session.add(row)
                await self.session.flush()
            return row

        if pool.pool_type == POOL_PERSONAL:
            if not pool.user_id:
                raise ValueError("user_id required for PERSONAL pool")
            return await self._get_or_create_personal(pool.user_id)

        raise ValueError(f"Unknown pool_type: {pool.pool_type}")

    async def _get_or_create_personal(self, user_id: UUID) -> UserGlobalPersonalSavings:
        stmt = select(UserGlobalPersonalSavings).where(
            UserGlobalPersonalSavings.user_id == user_id
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            row = UserGlobalPersonalSavings(user_id=user_id, total_savings=Decimal("0"))
            self.session.add(row)
            await self.session.flush()
        return row
