"""Ledger-backed savings operations (Family System V2)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import uuid6
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
        row = await self._get_or_create_pool_row(pool, lock=True)
        row.total_savings = row.total_savings + delta
        await self.session.flush()

    async def balance(self, pool: SavingsPoolRef, *, lock: bool = False) -> Decimal:
        row = await self._get_or_create_pool_row(pool, lock=lock)
        return Decimal(str(row.total_savings))

    async def lock_pools(self, pools: list[SavingsPoolRef]) -> None:
        """Lock several pools in a fixed order so two-sided moves can't deadlock."""
        def key(p: SavingsPoolRef) -> tuple[str, str]:
            return (p.pool_type, str(p.family_id or p.user_id))

        for pool in sorted(set(pools), key=key):
            await self._get_or_create_pool_row(pool, lock=True)

    async def _get_or_create_pool_row(
        self, pool: SavingsPoolRef, *, lock: bool = False
    ) -> FamilyTotalSavings | UserGlobalPersonalSavings:
        if pool.pool_type == POOL_FAMILY:
            if not pool.family_id:
                raise ValueError("family_id required for FAMILY pool")
            model, key_col, key = FamilyTotalSavings, "family_id", pool.family_id
        elif pool.pool_type == POOL_PERSONAL:
            if not pool.user_id:
                raise ValueError("user_id required for PERSONAL pool")
            model, key_col, key = UserGlobalPersonalSavings, "user_id", pool.user_id
        else:
            raise ValueError(f"Unknown pool_type: {pool.pool_type}")

        column = getattr(model, key_col)
        stmt = select(model).where(column == key)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row

        await self.session.execute(
            pg_insert(model.__table__)
            .values(
                id=uuid6.uuid7(),
                **{key_col: key},
                origin_amount=Decimal("0"),
                total_savings=Decimal("0"),
            )
            .on_conflict_do_nothing(index_elements=[key_col])
        )
        stmt = select(model).where(column == key).execution_options(populate_existing=True)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one()

    async def _get_or_create_personal(self, user_id: UUID) -> UserGlobalPersonalSavings:
        return await self._get_or_create_pool_row(  # type: ignore[return-value]
            SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id)
        )
