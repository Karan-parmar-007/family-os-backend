import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.scheduler.model import ScheduledJob
from app.api.schemas.pagination import PaginationParams
from app.core.constants import JOB_STATUS_AWAITING_CONFIRMATION
from app.core.job_action_service import JobActionService

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session
        self._actions = JobActionService(pg_session)

    async def list_family_jobs(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
        assigned_user_id: UUID | None = None,
    ) -> tuple[list[ScheduledJob], int]:
        filters = [ScheduledJob.family_id == family_id]
        if status:
            filters.append(ScheduledJob.status == status)
        if assigned_user_id:
            filters.append(ScheduledJob.assigned_user_id == assigned_user_id)

        count_stmt = select(func.count()).select_from(ScheduledJob).where(*filters)
        total = (await self.pg_session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ScheduledJob)
            .where(*filters)
            .order_by(ScheduledJob.scheduled_for.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        return list((await self.pg_session.execute(stmt)).scalars().all()), total

    async def list_my_jobs(
        self,
        user_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[ScheduledJob], int]:
        filters = [
            ScheduledJob.assigned_user_id == user_id,
            ScheduledJob.status == JOB_STATUS_AWAITING_CONFIRMATION,
        ]
        count_stmt = select(func.count()).select_from(ScheduledJob).where(*filters)
        total = (await self.pg_session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ScheduledJob)
            .where(*filters)
            .order_by(ScheduledJob.scheduled_for.asc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        return list((await self.pg_session.execute(stmt)).scalars().all()), total

    async def get_job(self, job_id: UUID, family_id: UUID) -> ScheduledJob | None:
        stmt = select(ScheduledJob).where(
            ScheduledJob.id == job_id,
            ScheduledJob.family_id == family_id,
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def job_action(
        self,
        job: ScheduledJob,
        user_id: UUID,
        action: str,
        *,
        delay_days: int | None = None,
        payload: dict | None = None,
    ) -> ScheduledJob:
        if job.assigned_user_id != user_id:
            raise PermissionError("Only the assigned user may act on this job")

        await self._actions.apply_action(
            job,
            None,
            action,
            delay_days=delay_days,
            actor_user_id=user_id,
            payload=payload,
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(job)
        return job

