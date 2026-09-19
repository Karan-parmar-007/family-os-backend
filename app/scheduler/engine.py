"""In-process scheduler tick for Family System V2."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.config import scheduler_settings
from app.core.constants import (
    JOB_STATUS_APPLIED,
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_DELAYED,
    JOB_STATUS_SCHEDULED,
    NOTIF_STATUS_UNREAD,
    allowed_actions_for_job_type,
)
from app.scheduler.jobs import apply_job
from app.scheduler.materialize import materialize_recurring_sources

logger = logging.getLogger(__name__)


async def try_advisory_lock(session: AsyncSession) -> bool:
    key = scheduler_settings.JOB_ADVISORY_LOCK_KEY
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": key},
    )
    return bool(result.scalar_one())


async def release_advisory_lock(session: AsyncSession) -> None:
    key = scheduler_settings.JOB_ADVISORY_LOCK_KEY
    await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


async def materialize_due_jobs(session: AsyncSession, now: datetime) -> int:
    """Flip due SCHEDULED jobs that need confirmation into AWAITING_CONFIRMATION."""
    stmt = select(ScheduledJob).where(
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(True),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    count = 0
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        if job.assigned_user_id:
            session.add(
                Notification(
                    user_id=job.assigned_user_id,
                    family_id=job.family_id,
                    type=job.job_type,
                    title=f"Confirm {job.job_type.replace('_', ' ').title()}",
                    body=f"Amount: {job.amount}",
                    related_job_id=job.id,
                    related_entity_type=job.source_type,
                    related_entity_id=job.source_id,
                    allowed_actions={
                        "actions": allowed_actions_for_job_type(job.job_type)
                    },
                    status=NOTIF_STATUS_UNREAD,
                )
            )
            count += 1
    await session.flush()
    return count


async def apply_auto_jobs(session: AsyncSession, now: datetime) -> int:
    """Apply due jobs that do not require confirmation."""
    stmt = select(ScheduledJob).where(
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(False),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        await apply_job(session, job)
    await session.flush()
    return len(jobs)


async def process_delayed_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.status == JOB_STATUS_DELAYED,
        ScheduledJob.next_retry_at <= now,
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        if job.assigned_user_id:
            session.add(
                Notification(
                    user_id=job.assigned_user_id,
                    family_id=job.family_id,
                    type=job.job_type,
                    title=f"Retry: {job.job_type.replace('_', ' ').title()}",
                    body=f"Amount: {job.amount}",
                    related_job_id=job.id,
                    related_entity_type=job.source_type,
                    related_entity_id=job.source_id,
                    allowed_actions={
                        "actions": allowed_actions_for_job_type(job.job_type)
                    },
                    status=NOTIF_STATUS_UNREAD,
                )
            )
    await session.flush()
    return len(jobs)


async def tick(session: AsyncSession) -> dict[str, int]:
    """Single scheduler tick. Caller must commit."""
    now = datetime.now(timezone.utc)
    from app.scheduler.income_cron import income_cron_tick
    from app.scheduler.expense_cron import expense_cron_tick
    from app.scheduler.debt_cron import debt_cron_tick
    from app.scheduler.investment_cron import investment_cron_tick
    from app.scheduler.insurance_cron import insurance_cron_tick
    from app.scheduler.savings_plan_cron import savings_plan_cron_tick
    from app.scheduler.transfer_cron import transfer_cron_tick

    income_stats = await income_cron_tick(session, now)
    expense_stats = await expense_cron_tick(session, now)
    debt_stats = await debt_cron_tick(session, now)
    investment_stats = await investment_cron_tick(session, now)
    insurance_stats = await insurance_cron_tick(session, now)
    savings_stats = await savings_plan_cron_tick(session, now)
    transfer_stats = await transfer_cron_tick(session, now)
    materialized_sources = await materialize_recurring_sources(session, now)
    materialized = await materialize_due_jobs(session, now)
    auto_applied = await apply_auto_jobs(session, now)
    retried = await process_delayed_jobs(session, now)
    return {
        **income_stats,
        **expense_stats,
        **debt_stats,
        **investment_stats,
        **insurance_stats,
        **savings_stats,
        **transfer_stats,
        "materialized_sources": materialized_sources,
        "materialized": materialized,
        "auto_applied": auto_applied,
        "retried": retried,
    }


async def run_tick_with_lock(session: AsyncSession) -> dict[str, int] | None:
    if not await try_advisory_lock(session):
        logger.debug("Scheduler tick skipped: advisory lock held")
        return None
    try:
        stats = await tick(session)
        await session.commit()
        return stats
    except Exception:
        await session.rollback()
        raise
    finally:
        await release_advisory_lock(session)
