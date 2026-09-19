"""Transfer cron — eager scheduling for recurring family transfers (Plan 08)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.api.routes.transfer.model import Transfer
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_AUTO_TRANSFER,
    NOTIF_STATUS_UNREAD,
    TRANSFER_STATUS_ACTIVE,
)
from app.core.notification_meta import add_job_notification
from app.core.period_key import period_key_for_date
from app.scheduler.jobs import SOURCE_TRANSFER

logger = logging.getLogger(__name__)

AUTO_ACCEPT_HOURS = 24


async def create_or_replace_next_transfer_job(
    session: AsyncSession,
    transfer: Transfer,
) -> ScheduledJob | None:
    if not transfer.is_recurring or transfer.next_run_date is None:
        return None
    if transfer.status not in (TRANSFER_STATUS_ACTIVE, "COMPLETED"):
        return None

    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == SOURCE_TRANSFER,
            ScheduledJob.source_id == transfer.id,
            ScheduledJob.job_type == JOB_TYPE_AUTO_TRANSFER,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    period_key = period_key_for_date(
        transfer.next_run_date, every=transfer.recurring_every or "MONTHLY"
    )
    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == SOURCE_TRANSFER,
                ScheduledJob.source_id == transfer.id,
                ScheduledJob.job_type == JOB_TYPE_AUTO_TRANSFER,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.amount = transfer.amount
        existing.scheduled_for = transfer.next_run_date
        existing.requires_confirmation = transfer.requires_confirmation
        existing.status = JOB_STATUS_SCHEDULED
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=transfer.family_id,
        job_type=JOB_TYPE_AUTO_TRANSFER,
        source_type=SOURCE_TRANSFER,
        source_id=transfer.id,
        amount=transfer.amount,
        direction="TRANSFER",
        period_key=period_key,
        scheduled_for=transfer.next_run_date,
        assigned_user_id=transfer.created_by,
        requires_confirmation=transfer.requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


async def _flip_due_transfer_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_AUTO_TRANSFER,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(True),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        await add_job_notification(
            session,
            job,
            title="Confirm transfer",
            body=f"Amount: {job.amount}. Auto-confirms in 24h.",
            entity_name="Transfer",
        )
    await session.flush()
    return len(jobs)


async def _auto_accept_transfer_jobs(session: AsyncSession, now: datetime) -> int:
    from app.scheduler.jobs import apply_job

    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_AUTO_TRANSFER,
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
            logger.exception("Auto-accept failed for transfer job %s", job.id)
    return applied


async def transfer_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    materialized = await _flip_due_transfer_jobs(session, when)
    auto_applied = await _auto_accept_transfer_jobs(session, when)
    return {
        "transfer_materialized": materialized,
        "transfer_auto_applied": auto_applied,
    }
