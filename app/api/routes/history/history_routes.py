from uuid import UUID

from fastapi import APIRouter, Query

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import FamilyMemberDep
from app.api.db_dependencies import PGSessionDep
from app.api.routes.history.history_schemas import HistoryItem, HistoryListResponse
from app.api.routes.history.history_service import HistoryService
from app.api.schemas.pagination import PaginationDep

router = APIRouter(tags=["history"])
family_router = APIRouter(prefix="/families/{family_id}/history", tags=["history"])
personal_router = APIRouter(prefix="/personal/history", tags=["history"])


@family_router.get("", response_model=HistoryListResponse)
async def family_history(
    family_id: UUID,
    _member: FamilyMemberDep,
    current_user: LoggedInUserDep,
    session: PGSessionDep,
    pagination: PaginationDep,
    entity_type: str | None = Query(default=None, alias="type"),
) -> HistoryListResponse:
    svc = HistoryService(session)
    items = await svc.list_family_history(
        family_id,
        current_user.id,
        entity_type=entity_type,
        limit=pagination.page_size,
    )
    return HistoryListResponse.from_page(items, total=len(items), pagination=pagination)


@personal_router.get("", response_model=HistoryListResponse)
async def personal_history(
    current_user: LoggedInUserDep,
    session: PGSessionDep,
    pagination: PaginationDep,
    entity_type: str | None = Query(default=None, alias="type"),
) -> HistoryListResponse:
    svc = HistoryService(session)
    items = await svc.list_personal_history(
        current_user.id,
        entity_type=entity_type,
        limit=pagination.page_size,
    )
    return HistoryListResponse.from_page(items, total=len(items), pagination=pagination)
