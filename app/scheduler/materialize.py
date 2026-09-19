"""Materialize scheduled_jobs from due recurring sources."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.model import FamilyExpense, PersonalExpense
from app.api.routes.goals.model import FamilyGoal, PersonalGoal
from app.api.routes.assets.model import FamilyAssets, PersonalAsset
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.savings_plans.model import FamilySavingsPlan, PersonalSavingsPlan
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_SCHEDULED,
    JOB_TYPE_DEBT_EMI,
    JOB_TYPE_DEBT_INTEREST_INCREASE,
    JOB_TYPE_GOAL_CONTRIB,
    JOB_TYPE_ASSET_EMI,
    JOB_TYPE_ASSET_VALUE_INCREASE,
    JOB_TYPE_INSURANCE_PREMIUM,
    JOB_TYPE_RECURRING_EXPENSE,
    JOB_TYPE_SAVINGS_PLAN_CONTRIB,
    NOTIF_STATUS_UNREAD,
    allowed_actions_for_job_type,
)
from app.core.period_key import period_key_for_date
from app.scheduler.jobs import (
    SOURCE_FAMILY_EXPENSE,
    SOURCE_FAMILY_GOAL,
    SOURCE_FAMILY_SAVINGS_PLAN,
    SOURCE_PERSONAL_EXPENSE,
    SOURCE_PERSONAL_GOAL,
    SOURCE_PERSONAL_SAVINGS_PLAN,
    SOURCE_TRANSFER,
    SOURCE_FAMILY_ASSET,
    SOURCE_PERSONAL_ASSET,
    SOURCE_FAMILY_INSURANCE,
    SOURCE_PERSONAL_INSURANCE,
    apply_job,
)

logger = logging.getLogger(__name__)


async def _job_exists(
    session: AsyncSession,
    source_type: str,
    source_id,
    period_key: str,
) -> bool:
    stmt = select(ScheduledJob.id).where(
        ScheduledJob.source_type == source_type,
        ScheduledJob.source_id == source_id,
        ScheduledJob.period_key == period_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _create_job(
    session: AsyncSession,
    *,
    family_id,
    job_type: str,
    source_type: str,
    source_id,
    amount: Decimal,
    direction: str,
    period_key: str,
    scheduled_for: datetime,
    assigned_user_id,
    requires_confirmation: bool,
) -> ScheduledJob | None:
    if await _job_exists(session, source_type, source_id, period_key):
        return None

    job = ScheduledJob(
        family_id=family_id,
        job_type=job_type,
        source_type=source_type,
        source_id=source_id,
        amount=amount,
        direction=direction,
        period_key=period_key,
        scheduled_for=scheduled_for,
        assigned_user_id=assigned_user_id,
        requires_confirmation=requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(job)
    await session.flush()
    return job


def _notify_for_job(session: AsyncSession, job: ScheduledJob) -> None:
    if not job.assigned_user_id:
        return
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
            allowed_actions={"actions": allowed_actions_for_job_type(job.job_type)},
            status=NOTIF_STATUS_UNREAD,
        )
    )


async def materialize_recurring_sources(session: AsyncSession, now: datetime) -> int:
    """Legacy fallback materializer.

    Debt EMIs (Plan 02), goal contributions (Plan 07, now manual-only),
    savings-plan contributions (Plan 06) and insurance premiums (Plan 05) are
    all handled by their own eager-scheduling crons (debt_cron.py,
    savings_plan_cron.py, insurance_cron.py) invoked directly from engine.py's
    tick(). This function only remains for the legacy (non-V2) FamilyExpense /
    PersonalExpense rows and auto-transfers that do not yet have a dedicated
    eager cron.
    """
    created = 0

    for model, source_type, is_personal in (
        (FamilyExpense, SOURCE_FAMILY_EXPENSE, False),
        (PersonalExpense, SOURCE_PERSONAL_EXPENSE, True),
    ):
        expenses = list(
            (
                await session.execute(
                    select(model).where(
                        model.is_recurring.is_(True),
                        model.next_payment_date.is_not(None),
                        model.next_payment_date <= now,
                    )
                )
            ).scalars().all()
        )
        for exp in expenses:
            pk = period_key_for_date(exp.next_payment_date, every=exp.paid_every)
            user_id = exp.user_id if is_personal else None
            job = await _create_job(
                session,
                family_id=exp.family_id,
                job_type=JOB_TYPE_RECURRING_EXPENSE,
                source_type=source_type,
                source_id=exp.id,
                amount=exp.amount,
                direction="DEDUCT",
                period_key=pk,
                scheduled_for=exp.next_payment_date,
                assigned_user_id=user_id,
                requires_confirmation=False,
            )
            if job:
                created += 1
                await apply_job(session, job)

    await session.flush()
    return created
