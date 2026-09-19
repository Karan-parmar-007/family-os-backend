"""Insurance premium cron — eager scheduling + lapse detection (Plan 05)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    NOTIF_STATUS_UNREAD,
)
from app.core.notification_meta import add_job_notification
from app.core.period_key import period_key_for_date

logger = logging.getLogger(__name__)

JOB_TYPE_INSURANCE_PREMIUM = "INSURANCE_PREMIUM"
SOURCE_FAMILY_INSURANCE = "FAMILY_INSURANCE"
SOURCE_PERSONAL_INSURANCE = "PERSONAL_INSURANCE"
AUTO_ACCEPT_HOURS = 24
MAX_CONSECUTIVE_SKIPS = 2


async def create_or_replace_next_premium_job(
    session: AsyncSession,
    ins: FamilyInsurance | PersonalInsurance,
    source_type: str,
) -> ScheduledJob | None:
    """Ensure one SCHEDULED INSURANCE_PREMIUM job for the next premium date."""
    if ins.next_premium_date is None or ins.premium_every is None:
        return None
    if ins.status not in ("ACTIVE",):
        return None

    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == ins.id,
            ScheduledJob.job_type == JOB_TYPE_INSURANCE_PREMIUM,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    family_id = ins.family_id if source_type == SOURCE_FAMILY_INSURANCE else None
    assigned = getattr(ins, "insured_user_id", None) or getattr(ins, "insured_member", None) or getattr(ins, "user_id", None)
    period_key = period_key_for_date(ins.next_premium_date, every=ins.premium_every)

    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == ins.id,
                ScheduledJob.job_type == JOB_TYPE_INSURANCE_PREMIUM,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.amount = ins.premium_amount
        existing.scheduled_for = ins.next_premium_date
        existing.status = JOB_STATUS_SCHEDULED
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=family_id,
        job_type=JOB_TYPE_INSURANCE_PREMIUM,
        source_type=source_type,
        source_id=ins.id,
        amount=ins.premium_amount,
        direction="OUT",
        period_key=period_key,
        scheduled_for=ins.next_premium_date,
        assigned_user_id=assigned,
        requires_confirmation=getattr(ins, "requires_confirmation", True),
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


async def _flip_due_insurance_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_INSURANCE_PREMIUM,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        ins_name = await _get_ins_name(session, job.source_id, job.source_type)
        await add_job_notification(
            session,
            job,
            title=f"Premium Due: {ins_name}",
            body=f"Amount: {job.amount}. Auto-confirms in 24h.",
            entity_name=ins_name,
        )
    await session.flush()
    return len(jobs)


async def _get_ins_name(session: AsyncSession, ins_id: UUID, source_type: str) -> str:
    if source_type == SOURCE_FAMILY_INSURANCE:
        ins = (await session.execute(select(FamilyInsurance).where(FamilyInsurance.id == ins_id))).scalar_one_or_none()
    else:
        ins = (await session.execute(select(PersonalInsurance).where(PersonalInsurance.id == ins_id))).scalar_one_or_none()
    return ins.insurance_name if ins else "Insurance"


async def _auto_accept_insurance_jobs(session: AsyncSession, now: datetime) -> int:
    from app.scheduler.jobs import apply_job
    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_INSURANCE_PREMIUM,
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
            logger.exception("Auto-accept failed for insurance job %s", job.id)
    return applied


async def insurance_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    materialized = await _flip_due_insurance_jobs(session, when)
    auto_applied = await _auto_accept_insurance_jobs(session, when)
    return {
        "insurance_premium_materialized": materialized,
        "insurance_auto_applied": auto_applied,
    }
