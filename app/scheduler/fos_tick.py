"""Family OS scheduler tick: recurring money rules, insurance installments, recurring transfers.

Only one tick runs at a time across workers (Postgres advisory lock). Each
item is committed separately so one failure can't block the rest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.routes.family.model import Family
from app.api.routes.profile.model import FosProfile
from app.api.routes.transfer.model import Transfer
from app.core.constants import TRANSFER_STATUS_ACTIVE, TRANSFER_STATUS_COMPLETED, TRANSFER_STATUS_PENDING
from app.core.funding_service import InsufficientFundsError
from app.core.tz_eighteen import local_date, step_eighteen_utc
from app.scheduler.insurance_installment_cron import run_insurance_installments
from app.scheduler.money_rule_cron import MAX_CATCH_UP, run_money_rules_cron

logger = logging.getLogger(__name__)

TICK_LOCK_KEY = 7_340_211


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


async def _run_parent(session: AsyncSession, parent_id: UUID, now: datetime, force: bool) -> int:
    from app.api.routes.transfer.transfer_service import TRANSFER_STATUS_FAILED, TransferService

    parent = (
        await session.execute(
            select(Transfer)
            .where(Transfer.id == parent_id, Transfer.status == TRANSFER_STATUS_ACTIVE)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if parent is None or parent.next_run_date is None:
        return 0
    service = TransferService(session)
    tz = await _scope_tz(session, family_id=parent.family_id, user_id=parent.from_user_id or parent.created_by)
    anchor = local_date(parent.next_run_date, tz).day
    created = 0
    while created < MAX_CATCH_UP and parent.status == TRANSFER_STATUS_ACTIVE:
        due = parent.next_run_date
        if due is None or (due > now and not (force and created == 0)):
            break
        if parent.end_date is not None and due > parent.end_date:
            parent.status = TRANSFER_STATUS_COMPLETED
            break
        direct = await service.is_direct_now(parent)
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
            via_code=not direct,
            requires_confirmation=not direct,
            show_breakdown_to_receiver=parent.show_breakdown_to_receiver,
            parent_id=parent.id,
            idempotency_key=f"run:{parent.id}:{local_date(due, tz).isoformat()}",
            status=TRANSFER_STATUS_PENDING,
            created_by=parent.created_by,
        )
        try:
            async with session.begin_nested():
                session.add(child)
                await session.flush()
        except IntegrityError:
            logger.info("Transfer %s already ran for %s", parent.id, due)
        else:
            if direct:
                try:
                    async with session.begin_nested():
                        await service.execute_transfer_run(child)
                except InsufficientFundsError as exc:
                    child.status = TRANSFER_STATUS_FAILED
                    child.failure_reason = (
                        f"Not enough balance: {exc.available:,.2f} available, {exc.required:,.2f} needed"
                    )
                    await service.notify_failed(child, child.failure_reason)
            else:
                await service._notify_offer(child)
            created += 1
        parent.next_run_date = step_eighteen_utc(
            due, tz, parent.recurring_every or "MONTHLY", anchor_day=anchor
        )
    if parent.end_date is not None and parent.next_run_date and parent.next_run_date > parent.end_date:
        parent.status = TRANSFER_STATUS_COMPLETED
    return created


async def run_recurring_transfers(
    session: AsyncSession, now: datetime | None = None, force: bool = False
) -> int:
    now = now or datetime.now(timezone.utc)
    stmt = select(Transfer.id).where(
        Transfer.is_recurring.is_(True),
        Transfer.status == TRANSFER_STATUS_ACTIVE,
        Transfer.next_run_date.is_not(None),
    )
    if not force:
        stmt = stmt.where(Transfer.next_run_date <= now)
    ids = list((await session.execute(stmt)).scalars().all())
    created = 0
    for parent_id in ids:
        try:
            created += await _run_parent(session, parent_id, now, force)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Recurring transfer %s failed", parent_id)
    return created


async def run_fos_tick(
    session: AsyncSession, now: datetime | None = None, force: bool = False
) -> dict:
    now = now or datetime.now(timezone.utc)
    # Session-level advisory locks belong to one connection, and the ORM session
    # returns its connection to the pool on every commit, so hold it separately.
    async with session.bind.connect() as lock_conn:
        got_lock = (
            await lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TICK_LOCK_KEY})
        ).scalar_one()
        if not got_lock:
            logger.info("Another scheduler tick is running; skipping")
            return {"skipped": True, "money_rules_applied": 0, "insurance_installments_paid": 0, "transfer_runs": 0}
        try:
            money = await run_money_rules_cron(session, now=now, force=force)
            insurance = await run_insurance_installments(session, now=now)
            transfers = await run_recurring_transfers(session, now=now, force=force)
            return {
                "money_rules_applied": money,
                "insurance_installments_paid": insurance,
                "transfer_runs": transfers,
                "forced": force,
            }
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TICK_LOCK_KEY})
            await lock_conn.commit()
