"""Dedicated income cron: eager job scheduling + due flip + auto-accept."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family_income.model import RecurringIncome, RecurringIncomeFamilySplit
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_RECURRING_INCOME,
    NOTIF_STATUS_ACTIONED,
    NOTIF_STATUS_DISMISSED,
    NOTIF_STATUS_UNREAD,
)
from app.core.notification_meta import add_job_notification
from app.scheduler.jobs import SOURCE_RECURRING_INCOME, apply_job

logger = logging.getLogger(__name__)

AUTO_ACCEPT_HOURS = 24


async def _first_split_family_id(session: AsyncSession, income_id: UUID) -> UUID | None:
    stmt = (
        select(RecurringIncomeFamilySplit.family_id)
        .where(RecurringIncomeFamilySplit.income_id == income_id)
        .order_by(RecurringIncomeFamilySplit.created_at.asc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def cancel_pending_income_jobs(session: AsyncSession, income_id: UUID) -> int:
    pending_stmt = select(ScheduledJob.id).where(
        ScheduledJob.source_type == SOURCE_RECURRING_INCOME,
        ScheduledJob.source_id == income_id,
        ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
    )
    job_ids = list((await session.execute(pending_stmt)).scalars().all())
    if job_ids:
        await session.execute(
            update(Notification)
            .where(Notification.related_job_id.in_(job_ids))
            .values(status=NOTIF_STATUS_DISMISSED)
        )
    stmt = (
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == SOURCE_RECURRING_INCOME,
            ScheduledJob.source_id == income_id,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount or 0


async def create_or_replace_next_job(
    session: AsyncSession,
    income: RecurringIncome,
) -> ScheduledJob | None:
    """Ensure exactly one pending job exists for the income's next occurrence."""
    await cancel_pending_income_jobs(session, income.id)

    if income.next_receiving_date is None:
        return None

    family_id = await _first_split_family_id(session, income.id)
    period_key = income.next_receiving_date.strftime("%Y-%m-%d")

    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == SOURCE_RECURRING_INCOME,
                ScheduledJob.source_id == income.id,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.family_id = family_id
        existing.amount = income.total_amount
        existing.scheduled_for = income.next_receiving_date
        existing.assigned_user_id = income.user_id
        existing.requires_confirmation = True
        existing.status = JOB_STATUS_SCHEDULED
        existing.awaiting_since = None
        existing.last_error = None
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=family_id,
        job_type=JOB_TYPE_RECURRING_INCOME,
        source_type=SOURCE_RECURRING_INCOME,
        source_id=income.id,
        amount=income.total_amount,
        direction="ADD",
        period_key=period_key,
        scheduled_for=income.next_receiving_date,
        assigned_user_id=income.user_id,
        requires_confirmation=True,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


async def _notify_for_job(session: AsyncSession, job: ScheduledJob) -> None:
    await add_job_notification(
        session,
        job,
        title="Confirm Recurring Income",
        body=(
            f"Amount: {job.amount}. "
            "Auto-confirms in 24h if no action is taken."
        ),
        entity_name="Recurring Income",
    )


async def _flip_due_income_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_RECURRING_INCOME,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        await _notify_for_job(session, job)
    await session.flush()
    return len(jobs)


async def _auto_accept_stale_income_jobs(session: AsyncSession, now: datetime) -> int:
    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_RECURRING_INCOME,
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
            logger.exception("auto-accept failed for income job %s", job.id)
    await session.flush()
    return applied


async def income_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    materialized = await _flip_due_income_jobs(session, when)
    auto_applied = await _auto_accept_stale_income_jobs(session, when)
    return {"income_materialized": materialized, "income_auto_applied": auto_applied}
