from uuid import UUID

from fastapi import APIRouter, Query

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import UpcomingServiceDep
from app.api.routes.upcoming.upcoming_schemas import UpcomingResponse

router = APIRouter(prefix="/families/{family_id}/upcoming", tags=["upcoming"])
personal_router = APIRouter(prefix="/upcoming", tags=["upcoming"])


@router.get("", response_model=UpcomingResponse)
async def list_upcoming(
    family_member: LoggedInFamilyMemberDep,
    upcoming_service: UpcomingServiceDep,
    family_id: UUID,
    horizon_days: int = Query(default=90, ge=1, le=730),
    scope: str | None = Query(default=None),
) -> UpcomingResponse:
    items = await upcoming_service.project_upcoming(
        family_id,
        family_member.id,
        horizon_days=horizon_days,
        scope=scope,
    )
    return UpcomingResponse(horizon_days=horizon_days, items=items)


@personal_router.get("", response_model=UpcomingResponse)
async def list_personal_upcoming(
    current_user: LoggedInUserDep,
    upcoming_service: UpcomingServiceDep,
    horizon_days: int = Query(default=90, ge=1, le=730),
) -> UpcomingResponse:
    items = await upcoming_service.project_upcoming(
        None,
        current_user.id,
        horizon_days=horizon_days,
        scope="personal",
    )
    return UpcomingResponse(horizon_days=horizon_days, items=items)
