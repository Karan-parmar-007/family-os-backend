"""Debt EMI cron — eager scheduling + due flip + auto-accept (Family System V2 – Plan 02).

Follows the same pattern as income_cron.py.
Integrated into engine.py tick via `debt_cron_tick`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.model import Debt, DebtScopeView
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_DEBT_EMI,
    NOTIF_STATUS_ACTIONED,
    NOTIF_STATUS_DISMISSED,
    NOTIF_STATUS_UNREAD,
    SOURCE_DEBT,
)
from app.core.notification_meta import add_job_notification
from app.core.period_key import period_key_for_date
from app.scheduler.jobs import (
    JOB_TYPE_DEBT_INTEREST_INCREASE,
    apply_job,
)

logger = logging.getLogger(__name__)

AUTO_ACCEPT_HOURS = 24


async def _job_family_id(session: AsyncSession, debt: Debt) -> UUID | None:
    primary_scope = (
        await session.execute(
            select(DebtScopeView.scope_kind).where(
                DebtScopeView.debt_id == debt.id,
                DebtScopeView.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()
    return debt.primary_family_id if primary_scope == "FAMILY" else None


# ---------------------------------------------------------------------------
# Eagerly create next job for a debt
# ---------------------------------------------------------------------------


async def cancel_pending_debt_jobs(
    session: AsyncSession,
    debt_id: UUID,
    source_type: str = SOURCE_DEBT,
) -> int:
    """Cancel any SCHEDULED or AWAITING_CONFIRMATION debt EMI jobs for this debt."""
    source_type = SOURCE_DEBT
    pending_stmt = select(ScheduledJob.id).where(
        ScheduledJob.source_type == source_type,
        ScheduledJob.source_id == debt_id,
        ScheduledJob.job_type == JOB_TYPE_DEBT_EMI,
        ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
    )
    job_ids = list((await session.execute(pending_stmt)).scalars().all())
    if job_ids:
        await session.execute(
            update(Notification)
            .where(Notification.related_job_id.in_(job_ids))
            .values(status=NOTIF_STATUS_DISMISSED)
        )
    result = await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == debt_id,
            ScheduledJob.job_type == JOB_TYPE_DEBT_EMI,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )
    await session.flush()
    return result.rowcount or 0


async def create_or_replace_next_debt_job(
    session: AsyncSession,
    debt: Debt,
    source_type: str = SOURCE_DEBT,
) -> ScheduledJob | None:
    """Ensure exactly one pending canonical DEBT_EMI job."""
    source_type = SOURCE_DEBT
    if not debt.has_emi or debt.emi_next_date is None:
        return None
    if debt.status != "ACTIVE":
        return None

    await cancel_pending_debt_jobs(session, debt.id, source_type)

    assigned_user = debt.owner_user_id
    family_id = await _job_family_id(session, debt)
    amount = debt.emi_amount or 0

    period_key = period_key_for_date(debt.emi_next_date, every=debt.emi_every or "MONTHLY")

    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == debt.id,
                ScheduledJob.job_type == JOB_TYPE_DEBT_EMI,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.family_id = family_id
        existing.amount = amount
        existing.scheduled_for = debt.emi_next_date
        existing.assigned_user_id = assigned_user
        existing.requires_confirmation = debt.requires_confirmation
        existing.status = JOB_STATUS_SCHEDULED
        existing.awaiting_since = None
        existing.last_error = None
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=family_id,
        job_type=JOB_TYPE_DEBT_EMI,
        source_type=source_type,
        source_id=debt.id,
        amount=amount,
        direction="OUT",
        period_key=period_key,
        scheduled_for=debt.emi_next_date,
        assigned_user_id=assigned_user,
        requires_confirmation=debt.requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


# ---------------------------------------------------------------------------
# Tick helpers
# ---------------------------------------------------------------------------


async def _notify_for_debt_job(
    session: AsyncSession, job: ScheduledJob, debt_name: str
) -> None:
    await add_job_notification(
        session,
        job,
        title=f"EMI Due: {debt_name}",
        body=f"Amount: {job.amount}. Auto-confirms in 24h if no action taken.",
        entity_name=debt_name,
    )


async def _flip_due_debt_jobs(session: AsyncSession, now: datetime) -> int:
    """Flip due SCHEDULED DEBT_EMI jobs that require confirmation to AWAITING_CONFIRMATION."""
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_DEBT_EMI,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(True),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        debt_name = await _get_debt_name(session, job.source_id, job.source_type)
        await _notify_for_debt_job(session, job, debt_name)
    await session.flush()
    return len(jobs)


async def _get_debt_name(session: AsyncSession, debt_id: UUID, source_type: str) -> str:
    """Load debt name — always tries canonical Debt first."""
    debt = (await session.execute(select(Debt).where(Debt.id == debt_id))).scalar_one_or_none()
    if debt is None:
        return "Debt"
    return debt.debt_name


async def _auto_accept_stale_debt_jobs(session: AsyncSession, now: datetime) -> int:
    """Auto-accept DEBT_EMI jobs that have been awaiting > 24h."""
    from app.scheduler.jobs import apply_job

    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_DEBT_EMI,
        ScheduledJob.status == JOB_STATUS_AWAITING_CONFIRMATION,
        ScheduledJob.awaiting_since.is_not(None),
        ScheduledJob.awaiting_since <= cutoff,
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    applied = 0
    for job in jobs:
        try:
            await apply_job(session, job)
            notif_stmt = select(Notification).where(Notification.related_job_id == job.id)
            for notif in (await session.execute(notif_stmt)).scalars().all():
                notif.status = NOTIF_STATUS_ACTIONED
                notif.action_taken = "AUTO_ACCEPTED"
                notif.actioned_at = now
            applied += 1
        except Exception:
            logger.exception("auto-accept failed for debt EMI job %s", job.id)
    await session.flush()
    return applied


async def _materialize_due_interest_increases(session: AsyncSession, now: datetime) -> int:
    """Create and apply DEBT_INTEREST_INCREASE jobs for due floating-rate step-ups."""
    from decimal import Decimal

    created = 0
    # Query canonical Debt table only (Phase 1+)
    debts = list(
        (
            await session.execute(
                select(Debt).where(
                    Debt.has_interest.is_(True),
                    Debt.next_interest_increase_date.is_not(None),
                    Debt.next_interest_increase_date <= now,
                    Debt.status == "ACTIVE",
                )
            )
        ).scalars().all()
    )
    for debt in debts:
        pk = period_key_for_date(
            debt.next_interest_increase_date,
            every=debt.interest_increase_every,
        )
        existing = (
            await session.execute(
                select(ScheduledJob).where(
                    ScheduledJob.source_type == SOURCE_DEBT,
                    ScheduledJob.source_id == debt.id,
                    ScheduledJob.job_type == JOB_TYPE_DEBT_INTEREST_INCREASE,
                    ScheduledJob.period_key == pk,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        job = ScheduledJob(
            family_id=await _job_family_id(session, debt),
            job_type=JOB_TYPE_DEBT_INTEREST_INCREASE,
            source_type=SOURCE_DEBT,
            source_id=debt.id,
            amount=Decimal("0"),
            direction="ADJUST",
            period_key=pk,
            scheduled_for=debt.next_interest_increase_date,
            assigned_user_id=None,
            requires_confirmation=False,
            status=JOB_STATUS_SCHEDULED,
        )
        session.add(job)
        await session.flush()
        await apply_job(session, job)
        created += 1
    return created


async def debt_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    interest_applied = await _materialize_due_interest_increases(session, when)
    materialized = await _flip_due_debt_jobs(session, when)
    auto_applied = await _auto_accept_stale_debt_jobs(session, when)
    return {
        "debt_interest_increases": interest_applied,
        "debt_emi_materialized": materialized,
        "debt_emi_auto_applied": auto_applied,
    }
