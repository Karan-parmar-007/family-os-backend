"""Sync FundingBreakdownEntry rows for manual income/expense logs (Plan 12 §4)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.funding import FundingSourceInput
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    POOL_FAMILY,
    POOL_PERSONAL,
    SPLIT_POOL_CURRENT_FAMILY,
    SPLIT_POOL_OTHER_FAMILY,
    SPLIT_POOL_PERSONAL,
)
from app.core.funding_service import FundingBreakdownEntry
from app.core.split_log_helpers import fetch_log_funding_sources

ENTITY_FAMILY_INCOME_LOG = "FAMILY_INCOME_LOG"
ENTITY_FAMILY_EXPENSE_LOG = "FAMILY_EXPENSE_LOG"


def _breakdown_pool_type(source: FundingSourceInput, host_family_id: UUID) -> str:
    if source.pool_type == POOL_PERSONAL:
        return SPLIT_POOL_PERSONAL
    if source.family_id == host_family_id:
        return SPLIT_POOL_CURRENT_FAMILY
    return SPLIT_POOL_OTHER_FAMILY


async def sync_log_funding_breakdown(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    host_family_id: UUID,
    show_to_family: bool,
    direction: str,
    logged_by_user_id: UUID | None = None,
    funding_sources: list[FundingSourceInput] | None = None,
) -> None:
    """Create or remove breakdown entries visible to the host family."""
    await session.execute(
        delete(FundingBreakdownEntry).where(
            FundingBreakdownEntry.entity_type == entity_type,
            FundingBreakdownEntry.entity_id == entity_id,
        )
    )
    if not show_to_family:
        await session.flush()
        return

    sources = funding_sources
    if sources is None:
        sources = await fetch_log_funding_sources(session, entity_type, entity_id)
    if not sources:
        await session.flush()
        return

    for source in sources:
        pool_type = _breakdown_pool_type(source, host_family_id)
        user_id = logged_by_user_id if pool_type == SPLIT_POOL_PERSONAL else None
        session.add(
            FundingBreakdownEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                pool_type=pool_type,
                family_id=source.family_id if pool_type != SPLIT_POOL_PERSONAL else None,
                user_id=user_id,
                amount=source.amount,
                direction=direction,
            )
        )
    await session.flush()


async def log_ids_with_breakdown(
    session: AsyncSession,
    entity_type: str,
    log_ids: list[UUID],
) -> set[UUID]:
    if not log_ids:
        return set()
    rows = (
        await session.execute(
            select(FundingBreakdownEntry.entity_id).where(
                FundingBreakdownEntry.entity_type == entity_type,
                FundingBreakdownEntry.entity_id.in_(log_ids),
            )
        )
    ).scalars().all()
    return set(rows)
