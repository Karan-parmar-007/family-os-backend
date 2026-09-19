import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import SchedulerServiceDep
from app.api.routes.scheduler.scheduler_schemas import (
    JobActionRequest,
    ScheduledJobListResponse,
    ScheduledJobResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.config import feature_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/jobs", tags=["scheduled-jobs"])


def _require_scheduler() -> None:
    if not feature_settings.FEATURE_SCHEDULER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("", response_model=ScheduledJobListResponse)
async def list_family_jobs(
    family_member: LoggedInFamilyMemberDep,
    scheduler_service: SchedulerServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
    job_status: str | None = Query(default=None, alias="status"),
    assigned_user_id: UUID | None = Query(default=None),
) -> ScheduledJobListResponse:
    _require_scheduler()
    items, total = await scheduler_service.list_family_jobs(
        family_id,
        pagination,
        status=job_status,
        assigned_user_id=assigned_user_id,
    )
    return ScheduledJobListResponse.from_page(
        [ScheduledJobResponse.model_validate(i) for i in items],
        total=total,
        pagination=pagination,
    )


@router.get("/mine", response_model=ScheduledJobListResponse)
async def list_my_jobs(
    current_user: LoggedInUserDep,
    scheduler_service: SchedulerServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> ScheduledJobListResponse:
    _require_scheduler()
    items, total = await scheduler_service.list_my_jobs(current_user.id, pagination)
    return ScheduledJobListResponse.from_page(
        [ScheduledJobResponse.model_validate(i) for i in items],
        total=total,
        pagination=pagination,
    )


@router.get("/{job_id}", response_model=ScheduledJobResponse)
async def get_job(
    family_member: LoggedInFamilyMemberDep,
    scheduler_service: SchedulerServiceDep,
    family_id: UUID,
    job_id: UUID,
) -> ScheduledJobResponse:
    _require_scheduler()
    job = await scheduler_service.get_job(job_id, family_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return ScheduledJobResponse.model_validate(job)


@router.post("/{job_id}/action", response_model=ScheduledJobResponse)
async def job_action(
    current_user: LoggedInUserDep,
    scheduler_service: SchedulerServiceDep,
    request: JobActionRequest,
    family_id: UUID,
    job_id: UUID,
) -> ScheduledJobResponse:
    _require_scheduler()
    job = await scheduler_service.get_job(job_id, family_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    try:
        updated = await scheduler_service.job_action(
            job,
            current_user.id,
            request.action,
            delay_days=request.delay_days,
            payload=request.payload,
        )
        return ScheduledJobResponse.model_validate(updated)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
