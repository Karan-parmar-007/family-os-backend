"""Reschedule helper for scheduled jobs (Family System V2 – Plan 01).

Supports two modes:
- PERMANENT: update source entity's next_*_date + cancel/recreate job
- ONE_TIME:  move only the pending job's scheduled_for; store original_next_date
             in job.meta so the cron advances from the original base after apply.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import FamilyMemberDep
from app.api.db_dependencies import PGSessionDep as DbDep
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import (
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    NOTIF_STATUS_DISMISSED,
    SOURCE_DEBT,
)
from app.scheduler.jobs import (
    SOURCE_FAMILY_INSURANCE,
    SOURCE_FAMILY_SAVINGS_PLAN,
    SOURCE_PERSONAL_INSURANCE,
    SOURCE_PERSONAL_SAVINGS_PLAN,
    SOURCE_RECURRING_EXPENSE,
    SOURCE_RECURRING_INCOME,
    SOURCE_FAMILY_RECURRING_EXPENSE,
    SOURCE_FAMILY_RECURRING_INCOME,
)

router = APIRouter(tags=["scheduler"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RescheduleRequest(BaseModel):
    new_date: datetime
    mode: Literal["ONE_TIME", "PERMANENT"] = "PERMANENT"

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class RescheduleResponse(BaseModel):
    job_id: UUID
    scheduled_for: datetime
    mode: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Core logic (shared by family + personal routes)
# ---------------------------------------------------------------------------


async def reschedule_source(
    session: AsyncSession,
    job_id: UUID,
    new_date: datetime,
    mode: str,
    *,
    actor_user_id: UUID,
) -> ScheduledJob:
    """Reschedule a job, either permanently or one-time.

    Security: caller must verify ownership of the job's source entity before
    calling this; this function does NOT re-check ownership.
    """
    stmt = select(ScheduledJob).where(
        ScheduledJob.id == job_id,
        ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
    )
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise ValueError(f"Active job {job_id} not found")

    if mode == "ONE_TIME":
        # Store original date so the cron advances from it after apply
        original_date = job.scheduled_for
        meta = dict(job.meta or {})
        meta["original_next_date"] = original_date.isoformat()
        job.meta = meta
        job.scheduled_for = new_date
        # period_key stays as the original date's key
        await session.flush()
        return job

    # PERMANENT: update source entity's next date + cancel pending + recreate
    await _permanent_reschedule(session, job, new_date)
    return job


async def _permanent_reschedule(
    session: AsyncSession,
    job: ScheduledJob,
    new_date: datetime,
) -> None:
    """Update source entity next_date field and recreate next job."""
    st = job.source_type
    sid = job.source_id

    # Cancel the current pending job
    job.status = JOB_STATUS_CANCELLED
    # Dismiss associated notification if any
    await session.execute(
        update(Notification)
        .where(Notification.related_job_id == job.id)
        .values(status=NOTIF_STATUS_DISMISSED)
    )
    await session.flush()

    if st in (SOURCE_RECURRING_INCOME, SOURCE_FAMILY_RECURRING_INCOME):
        from app.api.routes.family_income.model import RecurringIncome
        from app.scheduler.income_cron import create_or_replace_next_job

        income = (await session.execute(select(RecurringIncome).where(RecurringIncome.id == sid))).scalar_one_or_none()
        if income:
            income.next_receiving_date = new_date
            await create_or_replace_next_job(session, income)
        return

    if st in (SOURCE_RECURRING_EXPENSE, SOURCE_FAMILY_RECURRING_EXPENSE):
        from app.api.routes.family_expense.model import RecurringExpense
        from app.scheduler.expense_cron import create_or_replace_next_job

        expense = (await session.execute(select(RecurringExpense).where(RecurringExpense.id == sid))).scalar_one_or_none()
        if expense:
            expense.next_payment_date = new_date
            await create_or_replace_next_job(session, expense)
        return

    if st == SOURCE_DEBT:
        from app.api.routes.debt.model import Debt
        from app.scheduler.debt_cron import create_or_replace_next_debt_job

        debt = (
            await session.execute(select(Debt).where(Debt.id == sid))
        ).scalar_one_or_none()
        if debt:
            debt.emi_next_date = new_date
            await create_or_replace_next_debt_job(session, debt, SOURCE_DEBT)
        return

    if st in (SOURCE_FAMILY_SAVINGS_PLAN, SOURCE_PERSONAL_SAVINGS_PLAN):
        from app.api.routes.savings_plans.model import FamilySavingsPlan, PersonalSavingsPlan
        from app.scheduler.materialize import create_next_savings_plan_job

        model = PersonalSavingsPlan if st == SOURCE_PERSONAL_SAVINGS_PLAN else FamilySavingsPlan
        plan = (await session.execute(select(model).where(model.id == sid))).scalar_one_or_none()
        if plan:
            plan.next_contribution_date = new_date
            await create_next_savings_plan_job(session, plan, st)
        return

    if st in (SOURCE_FAMILY_INSURANCE, SOURCE_PERSONAL_INSURANCE):
        from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
        from app.scheduler.materialize import create_next_insurance_job

        model = PersonalInsurance if st == SOURCE_PERSONAL_INSURANCE else FamilyInsurance
        ins = (await session.execute(select(model).where(model.id == sid))).scalar_one_or_none()
        if ins:
            ins.next_premium_date = new_date
            await create_next_insurance_job(session, ins, st)
        return

    # Fallback: just create a new job at the new date
    new_job = ScheduledJob(
        family_id=job.family_id,
        job_type=job.job_type,
        source_type=job.source_type,
        source_id=job.source_id,
        assigned_user_id=job.assigned_user_id,
        amount=job.amount,
        direction=job.direction,
        period_key=new_date.strftime("%Y-%m-%d"),
        scheduled_for=new_date,
        requires_confirmation=job.requires_confirmation,
        status=JOB_STATUS_SCHEDULED,
    )
    session.add(new_job)
    await session.flush()


# ---------------------------------------------------------------------------
# Family endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/families/{family_id}/jobs/{job_id}/reschedule",
    response_model=RescheduleResponse,
    status_code=status.HTTP_200_OK,
)
async def reschedule_family_job(
    family_id: UUID,
    job_id: UUID,
    request: RescheduleRequest,
    current_user: LoggedInUserDep,
    _member: FamilyMemberDep,
    db: DbDep,
) -> RescheduleResponse:
    """Reschedule a job that belongs to a family-scoped entity."""
    try:
        job = await reschedule_source(
            db,
            job_id,
            request.new_date,
            request.mode,
            actor_user_id=current_user.id,
        )
        await db.commit()
        return RescheduleResponse(
            job_id=job.id, scheduled_for=job.scheduled_for, mode=request.mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Personal (no-family) endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/reschedule",
    response_model=RescheduleResponse,
    status_code=status.HTTP_200_OK,
)
async def reschedule_personal_job(
    job_id: UUID,
    request: RescheduleRequest,
    current_user: LoggedInUserDep,
    db: DbDep,
) -> RescheduleResponse:
    """Reschedule a job that belongs to a personal entity of the logged-in user."""
    # Verify job ownership: the job must have assigned_user_id == current_user.id
    stmt = select(ScheduledJob).where(
        ScheduledJob.id == job_id,
        ScheduledJob.assigned_user_id == current_user.id,
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        job = await reschedule_source(
            db,
            job_id,
            request.new_date,
            request.mode,
            actor_user_id=current_user.id,
        )
        await db.commit()
        return RescheduleResponse(
            job_id=job.id, scheduled_for=job.scheduled_for, mode=request.mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
