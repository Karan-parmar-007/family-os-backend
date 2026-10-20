from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import UpcomingServiceDep
from app.api.routes.upcoming.upcoming_schemas import UpcomingItem, UpcomingResponse
from app.api.schemas.pagination import PaginationDep, PaginationParams

router = APIRouter(prefix="/families/{family_id}/upcoming", tags=["upcoming"])


def _page(items: list[UpcomingItem], pagination: PaginationParams, horizon_days: int) -> UpcomingResponse:
    total_in = sum((i.amount for i in items if i.direction == "IN"), Decimal("0"))
    total_out = sum((i.amount for i in items if i.direction == "OUT"), Decimal("0"))
    page = items[pagination.offset : pagination.offset + pagination.page_size]
    return UpcomingResponse.from_page(
        page,
        total=len(items),
        pagination=pagination,
        horizon_days=horizon_days,
        total_in=total_in,
        total_out=total_out,
    )
personal_router = APIRouter(prefix="/upcoming", tags=["upcoming"])


@router.get("", response_model=UpcomingResponse)
async def list_upcoming(
    family_member: LoggedInFamilyMemberDep,
    upcoming_service: UpcomingServiceDep,
    family_id: UUID,
    pagination: PaginationDep,
    horizon_days: int = Query(default=90, ge=1, le=730),
    scope: str | None = Query(default=None),
) -> UpcomingResponse:
    items = await upcoming_service.project_upcoming(
        family_id,
        family_member.id,
        horizon_days=horizon_days,
        scope=scope,
    )
    return _page(items, pagination, horizon_days)


@personal_router.get("", response_model=UpcomingResponse)
async def list_personal_upcoming(
    current_user: LoggedInUserDep,
    upcoming_service: UpcomingServiceDep,
    pagination: PaginationDep,
    horizon_days: int = Query(default=90, ge=1, le=730),
) -> UpcomingResponse:
    items = await upcoming_service.project_upcoming(
        None,
        current_user.id,
        horizon_days=horizon_days,
        scope="personal",
    )
    return _page(items, pagination, horizon_days)
