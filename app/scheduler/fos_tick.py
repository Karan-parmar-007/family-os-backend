"""Family OS rewrite tick: money rules + recurring transfer offers. No confirmations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.routes.family.model import Family
from app.api.routes.profile.model import FosProfile
from app.api.routes.transfer.model import Transfer
from app.core.constants import TRANSFER_STATUS_ACTIVE, TRANSFER_STATUS_PENDING
from app.core.date_advance import advance_next_date
from app.core.tz_eighteen import at_eighteen_utc
from app.scheduler.money_rule_cron import run_money_rules_cron

logger = logging.getLogger(__name__)


async def _scope_tz(session: AsyncSession, *, family_id: UUID | None, user_id: UUID | None) -> str:
    if family_id is not None:
        fam = await session.get(Family, family_id)
        if fam is not None and getattr(fam, "timezone", None):
            return fam.timezone
    if user_id is not None:
        profile = await session.get(FosProfile, user_id)
        if profile is not None:
            return profile.timezone
    return "Asia/Kolkata"


async def materialize_transfer_offers(
    session: AsyncSession, now: datetime | None = None, force: bool = False
) -> int:
    """Each due recurring transfer creates one PENDING child offer; does not debit."""
    now = now or datetime.now(timezone.utc)
    stmt = select(Transfer).where(
        Transfer.is_recurring.is_(True),
        Transfer.status == TRANSFER_STATUS_ACTIVE,
        Transfer.next_run_date.is_not(None),
    )
    if not force:
        stmt = stmt.where(Transfer.next_run_date <= now)
    parents = list((await session.execute(stmt)).scalars().all())
    created = 0
    for parent in parents:
        if parent.end_date is not None and parent.end_date < now:
            parent.status = "COMPLETED"
            continue
        child = Transfer(
            family_id=parent.family_id,
            to_family_id=parent.to_family_id,
            from_scope=parent.from_scope,
            to_scope=parent.to_scope,
            from_user_id=parent.from_user_id,
            to_user_id=parent.to_user_id,
            entity_type=parent.entity_type,
            amount=parent.amount,
            note=parent.note,
            is_recurring=False,
            requires_confirmation=True,
            status=TRANSFER_STATUS_PENDING,
            created_by=parent.created_by,
        )
        session.add(child)
        tz = await _scope_tz(
            session,
            family_id=parent.family_id,
            user_id=parent.from_user_id or parent.created_by,
        )
        nxt = advance_next_date(parent.next_run_date, every=parent.recurring_every or "MONTHLY")
        parent.next_run_date = at_eighteen_utc(nxt, tz)
        created += 1
    if created:
        await session.commit()
    return created


async def run_fos_tick(
    session: AsyncSession, now: datetime | None = None, force: bool = False
) -> dict:
    now = now or datetime.now(timezone.utc)
    money = await run_money_rules_cron(session, now=now, force=force)
    offers = await materialize_transfer_offers(session, now=now, force=force)
    return {"money_rules_applied": money, "transfer_offers": offers, "forced": force}
