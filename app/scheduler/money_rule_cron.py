"""Apply due recurring income/expense rules (FosMoneyRule).

Each rule is processed in its own transaction under a row lock
(FOR UPDATE SKIP LOCKED), so overlapping ticks or replicas never double-post.
The unique (rule_id, period_key) index is the final guard.

Missed periods (downtime) are posted one by one, up to MAX_CATCH_UP; older
periods beyond that are skipped. Expenses always post, even if the pool goes
negative; the family head (family pool) or owner (personal pool) is alerted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.simple_debt_models import FosDebt
from app.api.routes.family.model import Family
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.money.model import FosMoneyEvent, FosMoneyEventParty, FosMoneyRule
from app.api.routes.profile.model import FosProfile
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_RECURRING_EXPENSE,
    LEDGER_SOURCE_RECURRING_INCOME,
    POOL_FAMILY,
    POOL_PERSONAL,
)
from app.core.money_alerts import OverdraftAlert, queue_overdraft_alerts, send_overdraft_emails
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.tz_eighteen import local_date, step_eighteen_utc

logger = logging.getLogger(__name__)

MAX_CATCH_UP = 36


async def _rule_tz(session: AsyncSession, rule: FosMoneyRule) -> str:
    if rule.family_id is not None:
        fam = await session.get(Family, rule.family_id)
        if fam is not None and getattr(fam, "timezone", None):
            return fam.timezone
    owner = rule.owner_user_id or rule.created_by
    if owner is not None:
        profile = await session.get(FosProfile, owner)
        if profile is not None:
            return profile.timezone
    return "Asia/Kolkata"


def pool_for(scope: str, family_id: UUID | None, owner_user_id: UUID | None) -> SavingsPoolRef:
    if scope == "PERSONAL":
        return SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=owner_user_id)
    return SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_id)


def next_due(rule: FosMoneyRule, after: datetime, tz: str) -> datetime:
    return step_eighteen_utc(
        after, tz, rule.frequency, every_n=rule.every_n or 1, anchor_day=rule.anchor_day
    )


async def _apply_debt_and_legacy_insurance(
    session: AsyncSession, rule: FosMoneyRule, amount: Decimal
) -> None:
    if rule.debt_id:
        debt = await session.get(FosDebt, rule.debt_id, with_for_update=True)
        if debt and debt.status == "OPEN" and debt.add_emi_to_paid:
            total = Decimal(str(debt.amount))
            debt.amount_paid = min(total, Decimal(str(debt.amount_paid)) + amount)
            if debt.amount_paid >= total:
                debt.status = "SETTLED"
                rule.status = "COMPLETED"

    # Policies created before installment schedules still count down EMIs here.
    if rule.insurance_id and rule.emi_remaining is not None:
        rule.emi_remaining = max(0, int(rule.emi_remaining) - 1)
        if rule.emi_remaining == 0:
            rule.status = "COMPLETED"
            ins = await session.get(FamilyInsurance, rule.insurance_id) or await session.get(
                PersonalInsurance, rule.insurance_id
            )
            if ins is not None:
                ins.status = "COMPLETED"


async def _post_period(
    session: AsyncSession,
    rule: FosMoneyRule,
    *,
    due: datetime,
    occurred_at: datetime,
    tz: str,
) -> tuple[FosMoneyEvent, Decimal] | None:
    """Post one period. Returns (event, balance_after) or None if already posted."""
    amount = Decimal(str(rule.amount))
    event = FosMoneyEvent(
        rule_id=rule.id,
        scope=rule.scope,
        family_id=rule.family_id,
        owner_user_id=rule.owner_user_id,
        kind=rule.kind,
        name=rule.name,
        amount=amount,
        category_id=rule.category_id,
        document_id=rule.document_id,
        let_everyone_edit=rule.let_everyone_edit,
        occurred_at=occurred_at,
        period_key=local_date(due, tz),
        created_by=rule.created_by,
    )
    try:
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except IntegrityError:
        logger.info("Rule %s already posted for %s", rule.id, event.period_key)
        return None

    for party in rule.parties or []:
        session.add(
            FosMoneyEventParty(event_id=event.id, party_type=party.party_type, user_id=party.user_id)
        )

    ledger = SavingsLedgerService(session)
    is_income = rule.kind == "INCOME"
    await ledger.apply_movement(
        pool=pool_for(rule.scope, rule.family_id, rule.owner_user_id),
        amount=amount,
        direction=LEDGER_IN if is_income else LEDGER_OUT,
        source_type=LEDGER_SOURCE_RECURRING_INCOME if is_income else LEDGER_SOURCE_RECURRING_EXPENSE,
        source_id=event.id,
        description=f"Recurring {'income' if is_income else 'expense'}: {rule.name}",
        occurred_at=occurred_at,
    )
    balance_after = await ledger.balance(pool_for(rule.scope, rule.family_id, rule.owner_user_id))
    if not is_income:
        event.is_overdrawn = balance_after < 0
        await _apply_debt_and_legacy_insurance(session, rule, amount)
    return event, balance_after


async def run_rule(
    session: AsyncSession,
    rule_id: UUID,
    *,
    now: datetime,
    force: bool = False,
) -> tuple[int, list[OverdraftAlert]]:
    """Catch a single rule up to ``now``. Caller commits."""
    rule = (
        await session.execute(
            select(FosMoneyRule)
            .where(FosMoneyRule.id == rule_id, FosMoneyRule.status == "ACTIVE")
            .with_for_update(skip_locked=True, of=FosMoneyRule)
        )
    ).scalar_one_or_none()
    if rule is None or (not force and rule.next_run_at > now):
        return 0, []

    tz = await _rule_tz(session, rule)
    if rule.anchor_day is None:
        rule.anchor_day = local_date(rule.next_run_at, tz).day

    posted = 0
    steps = 0
    last_overdraft: tuple[FosMoneyEvent, Decimal] | None = None
    while rule.status == "ACTIVE" and steps < MAX_CATCH_UP:
        due = rule.next_run_at
        forced_now = force and steps == 0 and due > now
        if due > now and not forced_now:
            break
        if rule.end_at is not None and due > rule.end_at:
            rule.status = "COMPLETED"
            break

        result = await _post_period(
            session, rule, due=due, occurred_at=now if forced_now else due, tz=tz
        )
        if result is not None:
            posted += 1
            rule.run_count = (rule.run_count or 0) + 1
            if result[0].is_overdrawn:
                last_overdraft = result
        rule.last_run_at = due
        rule.next_run_at = next_due(rule, due, tz)
        steps += 1

        if rule.max_runs is not None and rule.run_count >= rule.max_runs:
            rule.status = "COMPLETED"
        elif rule.end_at is not None and rule.next_run_at > rule.end_at:
            rule.status = "COMPLETED"

    if rule.status == "ACTIVE" and rule.next_run_at <= now and steps >= MAX_CATCH_UP:
        skipped = 0
        while rule.next_run_at <= now:
            rule.next_run_at = next_due(rule, rule.next_run_at, tz)
            skipped += 1
        logger.warning("Rule %s: skipped %d periods beyond catch-up limit", rule.id, skipped)

    alerts: list[OverdraftAlert] = []
    if last_overdraft is not None:
        event, balance_after = last_overdraft
        alerts = await queue_overdraft_alerts(
            session,
            family_id=rule.family_id if rule.scope == "FAMILY" else None,
            owner_user_id=rule.owner_user_id if rule.scope == "PERSONAL" else None,
            rule_name=rule.name,
            amount=Decimal(str(rule.amount)),
            balance_after=balance_after,
            event_id=event.id,
        )
    return posted, alerts


async def run_money_rules_cron(
    session: AsyncSession,
    now: Optional[datetime] = None,
    family_id: Optional[UUID] = None,
    force: bool = False,
) -> int:
    now = now or datetime.now(timezone.utc)

    stmt = select(FosMoneyRule.id).where(FosMoneyRule.status == "ACTIVE")
    if not force:
        stmt = stmt.where(FosMoneyRule.next_run_at <= now)
    if family_id is not None:
        stmt = stmt.where(FosMoneyRule.family_id == family_id)
    rule_ids = list((await session.execute(stmt.order_by(FosMoneyRule.next_run_at))).scalars().all())

    applied = 0
    for rule_id in rule_ids:
        try:
            posted, alerts = await run_rule(session, rule_id, now=now, force=force)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Recurring rule %s failed", rule_id)
            continue
        applied += posted
        await send_overdraft_emails(alerts)
    return applied
