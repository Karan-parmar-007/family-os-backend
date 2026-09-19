"""Build notification meta snapshots for actionable job notifications (Plan 09)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import Family
from app.api.routes.family_income.model import (
    RecurringIncome,
    RecurringIncomeFamilySplit,
)
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import NOTIF_STATUS_UNREAD, allowed_actions_for_job_type


async def build_job_meta(
    session: AsyncSession,
    job: ScheduledJob,
    *,
    entity_name: str,
) -> dict[str, Any]:
    """Snapshot data the frontend needs to render an actionable notification card."""
    current_split: list[dict[str, str | None]] = []
    if job.source_type and job.source_id:
        from app.core.funding_service import FundingService

        fs = FundingService(session)
        lines = await fs.load_split_plan(job.source_type, job.source_id)
        if lines:
            current_split = [
                {
                    "poolType": ln.pool_type,
                    "familyId": str(ln.family_id) if ln.family_id else None,
                    "amount": str(ln.amount),
                }
                for ln in lines
            ]

    meta: dict[str, Any] = {
        "jobType": job.job_type,
        "entityName": entity_name,
        "amount": str(job.amount),
        "periodKey": job.period_key,
        "currentSplit": current_split,
    }

    if job.job_type == "RECURRING_INCOME" and job.source_id:
        income_splits = await _income_splits_meta(session, job.source_id)
        if income_splits:
            meta["incomeSplits"] = income_splits
            meta["personalAmount"] = str(
                (
                    await session.execute(
                        select(RecurringIncome.personal_savings_amount).where(
                            RecurringIncome.id == job.source_id
                        )
                    )
                ).scalar_one_or_none()
                or "0"
            )

    return meta


async def _income_splits_meta(
    session: AsyncSession, income_id: UUID
) -> list[dict[str, str]]:
    rows = (
        await session.execute(
            select(RecurringIncomeFamilySplit, Family.name)
            .join(Family, Family.id == RecurringIncomeFamilySplit.family_id)
            .where(RecurringIncomeFamilySplit.income_id == income_id)
        )
    ).all()
    return [
        {
            "familyId": str(split.family_id),
            "familyName": name,
            "amount": str(split.amount),
        }
        for split, name in rows
    ]


def make_job_notification(
    *,
    user_id: UUID,
    family_id: UUID | None,
    job: ScheduledJob,
    title: str,
    body: str,
    meta: dict[str, Any] | None = None,
) -> Notification:
    return Notification(
        user_id=user_id,
        family_id=family_id,
        type=job.job_type,
        title=title,
        body=body,
        related_job_id=job.id,
        related_entity_type=job.source_type,
        related_entity_id=job.source_id,
        allowed_actions={"actions": allowed_actions_for_job_type(job.job_type)},
        meta=meta,
        status=NOTIF_STATUS_UNREAD,
    )


async def add_job_notification(
    session: AsyncSession,
    job: ScheduledJob,
    *,
    title: str,
    body: str,
    entity_name: str | None = None,
) -> None:
    """Create a notification with meta snapshot for a due job."""
    if not job.assigned_user_id:
        return
    name = entity_name or job.job_type.replace("_", " ").title()
    meta = await build_job_meta(session, job, entity_name=name)
    session.add(
        make_job_notification(
            user_id=job.assigned_user_id,
            family_id=job.family_id,
            job=job,
            title=title,
            body=body,
            meta=meta,
        )
    )
