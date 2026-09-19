"""Investment contribution cron + maturity scan (Family System V2 – Plan 04)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.investments.model import (
    FamilyInvestment,
    PersonalInvestment,
    InvestmentTxn,
)
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    NOTIF_STATUS_ACTIONED,
    NOTIF_STATUS_DISMISSED,
    NOTIF_STATUS_UNREAD,
)
from app.core.notification_meta import add_job_notification
from app.core.date_advance import advance_next_date
from app.core.period_key import period_key_for_date

logger = logging.getLogger(__name__)

JOB_TYPE_INVESTMENT_CONTRIB = "INVESTMENT_CONTRIB"
JOB_TYPE_INVESTMENT_MATURITY = "INVESTMENT_MATURITY"
SOURCE_FAMILY_INVESTMENT = "FAMILY_INVESTMENT"
SOURCE_PERSONAL_INVESTMENT = "PERSONAL_INVESTMENT"
AUTO_ACCEPT_HOURS = 24


async def create_or_replace_next_contrib_job(
    session: AsyncSession,
    inv: FamilyInvestment | PersonalInvestment,
    source_type: str,
) -> ScheduledJob | None:
    """Ensure one SCHEDULED INVESTMENT_CONTRIB job for the next contribution date."""
    if not inv.has_recurring or inv.next_contribution_date is None:
        return None
    if inv.status != "ACTIVE":
        return None

    # Cancel existing pending jobs
    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == inv.id,
            ScheduledJob.job_type == JOB_TYPE_INVESTMENT_CONTRIB,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    family_id = inv.family_id if source_type == SOURCE_FAMILY_INVESTMENT else None
    assigned_user = getattr(inv, "in_someone_name", None) or getattr(inv, "user_id", None)

    period_key = period_key_for_date(
        inv.next_contribution_date, every=inv.contribution_every or "MONTHLY"
    )

    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == inv.id,
                ScheduledJob.job_type == JOB_TYPE_INVESTMENT_CONTRIB,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.amount = inv.contribution_amount or 0
        existing.scheduled_for = inv.next_contribution_date
        existing.status = JOB_STATUS_SCHEDULED
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=family_id,
        job_type=JOB_TYPE_INVESTMENT_CONTRIB,
        source_type=source_type,
        source_id=inv.id,
        amount=inv.contribution_amount or 0,
        direction="OUT",
        period_key=period_key,
        scheduled_for=inv.next_contribution_date,
        assigned_user_id=assigned_user,
        requires_confirmation=inv.requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


async def _flip_due_investment_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_INVESTMENT_CONTRIB,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(True),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        inv_name = await _get_inv_name(session, job.source_id, job.source_type)
        await add_job_notification(
            session,
            job,
            title=f"SIP/Contribution Due: {inv_name}",
            body=f"Amount: {job.amount}. Auto-confirms in 24h.",
            entity_name=inv_name,
        )
    await session.flush()
    return len(jobs)


async def _get_inv_name(session: AsyncSession, inv_id: UUID, source_type: str) -> str:
    if source_type == SOURCE_FAMILY_INVESTMENT:
        inv = (await session.execute(select(FamilyInvestment).where(FamilyInvestment.id == inv_id))).scalar_one_or_none()
    else:
        inv = (await session.execute(select(PersonalInvestment).where(PersonalInvestment.id == inv_id))).scalar_one_or_none()
    return inv.investment_name if inv else "Investment"


async def check_maturities(session: AsyncSession, now: datetime) -> int:
    """Check and process matured investments. Returns count processed."""
    processed = 0
    for model, source_type in [
        (FamilyInvestment, SOURCE_FAMILY_INVESTMENT),
        (PersonalInvestment, SOURCE_PERSONAL_INVESTMENT),
    ]:
        stmt = select(model).where(
            model.status == "ACTIVE",
            model.maturity_date <= now,
            model.maturity_date.is_not(None),
        )
        investments = list((await session.execute(stmt)).scalars().all())
        for inv in investments:
            period_key = f"MATURITY_{inv.maturity_date.strftime('%Y%m%d')}"
            # Idempotent
            existing_maturity_job = (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.source_type == source_type,
                        ScheduledJob.source_id == inv.id,
                        ScheduledJob.job_type == JOB_TYPE_INVESTMENT_MATURITY,
                        ScheduledJob.period_key == period_key,
                    )
                )
            ).scalar_one_or_none()
            if existing_maturity_job:
                continue

            if inv.auto_credit_on_maturity:
                # Auto-apply
                await _apply_maturity(session, inv, source_type, now)
            else:
                # Create notification job
                assigned = getattr(inv, "in_someone_name", None) or getattr(inv, "user_id", None)
                job = ScheduledJob(
                    family_id=inv.family_id,
                    job_type=JOB_TYPE_INVESTMENT_MATURITY,
                    source_type=source_type,
                    source_id=inv.id,
                    amount=inv.maturity_amount or inv.current_value,
                    direction="IN",
                    period_key=period_key,
                    scheduled_for=now,
                    assigned_user_id=assigned,
                    requires_confirmation=True,
                    status=JOB_STATUS_AWAITING_CONFIRMATION,
                )
                session.add(job)
                await session.flush()
                if assigned:
                    session.add(Notification(
                        user_id=assigned,
                        family_id=inv.family_id,
                        type=JOB_TYPE_INVESTMENT_MATURITY,
                        title=f"Investment Matured: {inv.investment_name}",
                        body=f"Value: {inv.maturity_amount or inv.current_value}. Accept to credit your account.",
                        related_job_id=job.id,
                        related_entity_type=source_type,
                        related_entity_id=inv.id,
                        allowed_actions={"actions": ["ACCEPT", "DISMISS"]},
                        status=NOTIF_STATUS_UNREAD,
                    ))
            processed += 1
    await session.flush()
    return processed


async def _apply_maturity(
    session: AsyncSession,
    inv: FamilyInvestment | PersonalInvestment,
    source_type: str,
    now: datetime,
) -> None:
    """Credit maturity value to pool + create income log + mark MATURED."""
    from app.core.constants import LEDGER_IN
    from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
    from app.core.transfer_pools import scope_to_pool

    maturity_val = inv.maturity_amount or inv.current_value
    if not maturity_val:
        from app.core.interest_math import compute_compound_maturity, compute_simple_maturity
        if inv.return_type == "COMPOUND" and inv.annual_return_rate and inv.tenure_months:
            maturity_val = compute_compound_maturity(
                inv.invested_amount,
                inv.annual_return_rate,
                inv.tenure_months / 12,
                inv.compounding_frequency or "YEARLY",
            )
        elif inv.return_type == "SIMPLE" and inv.annual_return_rate and inv.tenure_months:
            maturity_val = compute_simple_maturity(
                inv.invested_amount, inv.annual_return_rate, inv.tenure_months / 12
            )
        else:
            maturity_val = inv.current_value or inv.invested_amount

    is_personal = source_type == SOURCE_PERSONAL_INVESTMENT
    pool = scope_to_pool(
        "PERSONAL" if is_personal else "FAMILY",
        family_id=inv.family_id,
        user_id=getattr(inv, "user_id", None) if is_personal else None,
    )
    ledger = SavingsLedgerService(session)
    await ledger.apply_movement(
        pool, maturity_val, LEDGER_IN, "INVESTMENT_MATURITY",
        source_id=inv.id,
        description=f"Investment matured — {inv.investment_name}",
        occurred_at=now,
    )

    # InvestmentTxn record
    txn = InvestmentTxn(
        investment_scope="PERSONAL" if is_personal else "FAMILY",
        investment_id=inv.id,
        txn_type="MATURITY_CREDIT",
        amount=maturity_val,
        direction="IN",
        occurred_at=now,
        source_type="SCHEDULED",
    )
    session.add(txn)

    inv.status = "MATURED"
    inv.completed_at = now
    inv.current_value = maturity_val

    # Cancel pending contrib jobs
    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == inv.id,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    try:
        from app.utils.email_recipients import resolve_user_email
        from app.utils.finance_emails import send_investment_matured_email

        owner_email = await resolve_user_email(session, getattr(inv, "user_id", None))
        if owner_email:
            await send_investment_matured_email(
                session,
                owner_email=owner_email,
                investment_name=inv.investment_name,
                matured_amount=maturity_val,
                credited_pool_label="Savings pool",
                family_id=inv.family_id,
            )
    except Exception:
        logger.exception("Failed to send investment matured email for %s", inv.id)


async def _auto_accept_investment_jobs(session: AsyncSession, now: datetime) -> int:
    from app.scheduler.jobs import apply_job
    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_INVESTMENT_CONTRIB,
        ScheduledJob.status == JOB_STATUS_AWAITING_CONFIRMATION,
        ScheduledJob.awaiting_since.is_not(None),
        ScheduledJob.awaiting_since <= cutoff,
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    applied = 0
    for job in jobs:
        try:
            await apply_job(session, job)
            applied += 1
        except Exception:
            logger.exception("Auto-accept failed for investment job %s", job.id)
    return applied


async def investment_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    materialized = await _flip_due_investment_jobs(session, when)
    matured = await check_maturities(session, when)
    auto_applied = await _auto_accept_investment_jobs(session, when)
    return {
        "investment_contrib_materialized": materialized,
        "investment_matured": matured,
        "investment_auto_applied": auto_applied,
    }
