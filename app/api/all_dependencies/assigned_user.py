"""Dependency: caller must be the assigned user for a scheduled job."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.db_dependencies import PGSessionDep
from app.api.routes.scheduler.model import ScheduledJob
from app.api.routes.user.model import UserBase


async def get_assigned_user_for_job(
    current_user: LoggedInUserDep,
    job_id: UUID,
    family_id: UUID,
    session: PGSessionDep,
) -> tuple[UserBase, ScheduledJob]:
    stmt = select(ScheduledJob).where(
        ScheduledJob.id == job_id,
        ScheduledJob.family_id == family_id,
    )
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned user may act on this job",
        )
    return current_user, job


type LoggedInAssigneeDep = Annotated[
    tuple[UserBase, ScheduledJob],
    Depends(get_assigned_user_for_job),
]
