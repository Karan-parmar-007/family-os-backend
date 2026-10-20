"""Charge due insurance installments.

Each due PENDING installment becomes one expense entry and one ledger debit,
in its own transaction under a row lock (SKIP LOCKED). Interval policies get
their next policy year generated once the current year has been charged.
Like recurring expenses, a premium is always recorded even if the balance goes
negative; heads (family policy) or the owner (personal policy) are alerted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.insurance.insurance_service import InsuranceService
from app.api.routes.insurance.model import FamilyInsurance, FosInsuranceInstallment, PersonalInsurance
from app.api.routes.money.model import FosMoneyEvent
from app.api.routes.user.model import UserFamilyLink
from app.core.constants import LEDGER_OUT, LEDGER_SOURCE_INSURANCE_PREMIUM
from app.core.money_alerts import OverdraftAlert, queue_overdraft_alerts, send_overdraft_emails
from app.core.savings_ledger_service import SavingsLedgerService
from app.core.tz_eighteen import step_eighteen_utc
from app.scheduler.money_rule_cron import pool_for

logger = logging.getLogger(__name__)


async def _actor_for(session: AsyncSession, ins: FamilyInsurance | PersonalInsurance) -> UUID | None:
    if isinstance(ins, PersonalInsurance):
        return ins.user_id
    if ins.created_by:
        return ins.created_by
    if ins.insured_member:
        return ins.insured_member
    stmt = select(UserFamilyLink.user_id).where(
        UserFamilyLink.family_id == ins.family_id, UserFamilyLink.is_family_manager.is_(True)
    )
    return (await session.execute(stmt)).scalars().first()


async def _extend_interval_year(service: InsuranceService, ins, last_due: datetime) -> None:
    pending = (
        await service.pg_session.execute(
            select(func.count())
            .select_from(FosInsuranceInstallment)
            .where(
                FosInsuranceInstallment.insurance_id == ins.id,
                FosInsuranceInstallment.status == "PENDING",
            )
        )
    ).scalar_one()
    if pending or not ins.annual_premium or not ins.premium_every:
        return
    tz = await service.policy_tz(ins)
    first = step_eighteen_utc(last_due, tz, ins.premium_every)
    if ins.end_date is not None and first > ins.end_date:
        ins.status = "COMPLETED"
        ins.completed_at = datetime.now(timezone.utc)
        return
    await service.generate_interval_year(ins, first, tz)


async def charge_installment(
    session: AsyncSession, installment_id: UUID, now: datetime
) -> tuple[bool, list[OverdraftAlert]]:
    inst = (
        await session.execute(
            select(FosInsuranceInstallment)
            .where(
                FosInsuranceInstallment.id == installment_id,
                FosInsuranceInstallment.status == "PENDING",
                FosInsuranceInstallment.due_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if inst is None:
        return False, []
    model = PersonalInsurance if inst.is_personal else FamilyInsurance
    ins = await session.get(model, inst.insurance_id, with_for_update=True)
    if ins is None or ins.status != "ACTIVE":
        inst.status = "CANCELLED"
        return False, []

    scope = "PERSONAL" if inst.is_personal else "FAMILY"
    family_id = None if inst.is_personal else ins.family_id
    owner = ins.user_id if inst.is_personal else None
    actor = await _actor_for(session, ins)
    if actor is None:
        logger.warning("Insurance %s has no one to record the premium as; skipped", ins.id)
        return False, []

    amount = Decimal(str(inst.amount))
    event = FosMoneyEvent(
        scope=scope,
        family_id=family_id,
        owner_user_id=owner,
        kind="EXPENSE",
        name=f"Insurance premium: {ins.insurance_name}",
        amount=amount,
        let_everyone_edit=False,
        occurred_at=inst.due_at,
        created_by=actor,
    )
    session.add(event)
    await session.flush()

    ledger = SavingsLedgerService(session)
    pool = pool_for(scope, family_id, owner)
    await ledger.apply_movement(
        pool,
        amount,
        LEDGER_OUT,
        LEDGER_SOURCE_INSURANCE_PREMIUM,
        source_id=event.id,
        description=event.name,
        occurred_at=inst.due_at,
    )
    balance_after = await ledger.balance(pool)
    event.is_overdrawn = balance_after < 0
    inst.status = "PAID"
    inst.paid_at = now
    inst.paid_event_id = event.id

    service = InsuranceService(session)
    if ins.schedule_mode == "INTERVAL":
        await _extend_interval_year(service, ins, inst.due_at)
    await session.flush()
    await service.refresh_next_due(ins)

    alerts: list[OverdraftAlert] = []
    if event.is_overdrawn:
        alerts = await queue_overdraft_alerts(
            session,
            family_id=family_id,
            owner_user_id=owner,
            rule_name=event.name,
            amount=amount,
            balance_after=balance_after,
            event_id=event.id,
        )
    return True, alerts


async def run_insurance_installments(session: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    ids = list(
        (
            await session.execute(
                select(FosInsuranceInstallment.id)
                .where(FosInsuranceInstallment.status == "PENDING", FosInsuranceInstallment.due_at <= now)
                .order_by(FosInsuranceInstallment.due_at)
            )
        ).scalars().all()
    )
    paid = 0
    for inst_id in ids:
        try:
            ok, alerts = await charge_installment(session, inst_id, now)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Insurance installment %s failed", inst_id)
            continue
        paid += int(ok)
        await send_overdraft_emails(alerts)
    return paid
