"""Savings plan contribution cron — eager scheduling + skip/completion (Plan 06)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.savings_plans.model import FamilySavingsPlan, PersonalSavingsPlan
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

JOB_TYPE_SAVINGS_PLAN_CONTRIB = "SAVINGS_PLAN_CONTRIB"
SOURCE_FAMILY_SAVINGS_PLAN = "FAMILY_SAVINGS_PLAN"
SOURCE_PERSONAL_SAVINGS_PLAN = "PERSONAL_SAVINGS_PLAN"
AUTO_ACCEPT_HOURS = 24


async def create_or_replace_next_contrib_job(
    session: AsyncSession,
    plan: FamilySavingsPlan | PersonalSavingsPlan,
    source_type: str,
) -> ScheduledJob | None:
    """Ensure one SCHEDULED SAVINGS_PLAN_CONTRIB job for the next contribution date."""
    if not plan.contribution_amount or plan.next_contribution_date is None:
        return None
    if plan.status not in ("ACTIVE", "PAUSED"):
        return None

    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == plan.id,
            ScheduledJob.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    family_id = plan.family_id if source_type == SOURCE_FAMILY_SAVINGS_PLAN else None
    assigned = getattr(plan, "user_id", None)  # personal plans
    period_key = period_key_for_date(
        plan.next_contribution_date, every=plan.contribution_every or "MONTHLY"
    )

    existing = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.source_type == source_type,
                ScheduledJob.source_id == plan.id,
                ScheduledJob.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB,
                ScheduledJob.period_key == period_key,
            )
        )
    ).scalar_one_or_none()

    requires_confirmation = getattr(plan, "requires_confirmation", False)

    if existing:
        existing.amount = plan.contribution_amount
        existing.scheduled_for = plan.next_contribution_date
        existing.status = JOB_STATUS_SCHEDULED
        await session.flush()
        return existing

    job = ScheduledJob(
        family_id=family_id,
        job_type=JOB_TYPE_SAVINGS_PLAN_CONTRIB,
        source_type=source_type,
        source_id=plan.id,
        amount=plan.contribution_amount,
        direction="OUT",
        period_key=period_key,
        scheduled_for=plan.next_contribution_date,
        assigned_user_id=assigned,
        requires_confirmation=requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


async def _flip_due_savings_jobs(session: AsyncSession, now: datetime) -> int:
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB,
        ScheduledJob.status == JOB_STATUS_SCHEDULED,
        ScheduledJob.scheduled_for <= now,
        ScheduledJob.requires_confirmation.is_(True),
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = JOB_STATUS_AWAITING_CONFIRMATION
        job.awaiting_since = now
        plan_name = await _get_plan_name(session, job.source_id, job.source_type)
        await add_job_notification(
            session,
            job,
            title=f"Savings Plan Contribution Due: {plan_name}",
            body=f"Amount: {job.amount}. Auto-confirms in 24h.",
            entity_name=plan_name,
        )
    await session.flush()
    return len(jobs)


async def _get_plan_name(session: AsyncSession, plan_id: UUID, source_type: str) -> str:
    if source_type == SOURCE_FAMILY_SAVINGS_PLAN:
        plan = (await session.execute(select(FamilySavingsPlan).where(FamilySavingsPlan.id == plan_id))).scalar_one_or_none()
    else:
        plan = (await session.execute(select(PersonalSavingsPlan).where(PersonalSavingsPlan.id == plan_id))).scalar_one_or_none()
    return plan.plan_name if plan else "Savings Plan"


async def check_completion(
    session: AsyncSession,
    plan: FamilySavingsPlan | PersonalSavingsPlan,
    source_type: str,
) -> bool:
    """Check if plan is complete. Returns True if completed."""
    if plan.accumulated_amount < plan.target_amount:
        return False

    from app.core.default_bucket_service import DefaultBucketService
    bucket_svc = DefaultBucketService(session)
    open_total = await bucket_svc.total_open(source_type, plan.id)
    if open_total > Decimal("0"):
        return False

    plan.status = "COMPLETED"
    plan.completed_at = datetime.now(timezone.utc)
    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == source_type,
            ScheduledJob.source_id == plan.id,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )

    try:
        from app.utils.email_recipients import resolve_user_email
        from app.utils.finance_emails import send_savings_plan_completed_email

        owner_email = await resolve_user_email(session, getattr(plan, "user_id", None))
        if owner_email:
            await send_savings_plan_completed_email(
                session,
                owner_email=owner_email,
                plan_name=plan.plan_name,
                target_amount=plan.target_amount,
                family_id=plan.family_id,
            )
    except Exception:
        logger.exception("Failed to send savings plan completion email for %s", plan.id)

    await session.flush()
    return True


async def _auto_accept_savings_jobs(session: AsyncSession, now: datetime) -> int:
    from app.scheduler.jobs import apply_job
    cutoff = now - timedelta(hours=AUTO_ACCEPT_HOURS)
    stmt = select(ScheduledJob).where(
        ScheduledJob.job_type == JOB_TYPE_SAVINGS_PLAN_CONTRIB,
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
            logger.exception("Auto-accept failed for savings plan job %s", job.id)
    return applied


async def savings_plan_cron_tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    when = now or datetime.now(timezone.utc)
    materialized = await _flip_due_savings_jobs(session, when)
    auto_applied = await _auto_accept_savings_jobs(session, when)
    return {
        "savings_plan_materialized": materialized,
        "savings_plan_auto_applied": auto_applied,
    }
