"""Personal goals routes — /api/personal/goals (Plan 07)."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import GoalsServiceDep
from app.api.routes.goals.goals_routes import _resp
from app.api.routes.goals.goals_schemas import (
    GoalContributionCreateRequest,
    GoalContributionListResponse,
    GoalContributionResponse,
    GoalCreateRequest,
    GoalListResponse,
    GoalResponse,
    GoalUpdateRequest,
    GoalWithdrawRequest,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/personal/goals", tags=["personal-goals"])


@router.get("", response_model=GoalListResponse)
async def list_personal_goals(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    pagination: PaginationDep,
    status: str | None = Query(default="ACTIVE"),
) -> GoalListResponse:
    items, total = await goals_service.list_personal_goals(
        user.id, pagination, status=status
    )
    return GoalListResponse.from_page(
        [_resp(g, True) for g in items], total=total, pagination=pagination
    )


@router.get("/history", response_model=GoalListResponse)
async def personal_goal_history(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    pagination: PaginationDep,
) -> GoalListResponse:
    items, total = await goals_service.list_personal_goals(
        user.id, pagination, status=None
    )
    history = [g for g in items if g.status in ("ACHIEVED", "CANCELLED")]
    return GoalListResponse.from_page(
        [_resp(g, True) for g in history], total=len(history), pagination=pagination
    )


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_goal(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    request: GoalCreateRequest,
    family_id: UUID,
) -> GoalResponse:
    goal = await goals_service.create_personal_goal(user.id, family_id, request)
    return _resp(goal, True)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_personal_goal(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    goal_id: UUID,
) -> GoalResponse:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _resp(goal, True)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_personal_goal(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    request: GoalUpdateRequest,
    goal_id: UUID,
) -> GoalResponse:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    updated = await goals_service.update_goal(goal, request)
    return _resp(updated, True)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_goal(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    goal_id: UUID,
) -> None:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await goals_service.delete_goal(goal, True, user.id)


@router.get("/{goal_id}/contributions", response_model=GoalContributionListResponse)
async def list_personal_goal_contributions(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    goal_id: UUID,
) -> GoalContributionListResponse:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    items = await goals_service.list_contributions(goal_id, goal.family_id, True)
    return GoalContributionListResponse(
        items=[GoalContributionResponse.model_validate(i) for i in items]
    )


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_personal_goal_contribution(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    request: GoalContributionCreateRequest,
    goal_id: UUID,
) -> GoalContributionResponse:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        contrib = await goals_service.add_contribution(goal, True, user.id, request)
        return GoalContributionResponse.model_validate(contrib)
    except ValueError as exc:
        await goals_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{goal_id}/withdraw",
    response_model=GoalContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def withdraw_personal_goal(
    user: LoggedInUserDep,
    goals_service: GoalsServiceDep,
    request: GoalWithdrawRequest,
    goal_id: UUID,
) -> GoalContributionResponse:
    goal = await goals_service.get_personal_goal(goal_id, user.id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        contrib = await goals_service.withdraw(goal, True, user.id, request)
        return GoalContributionResponse.model_validate(contrib)
    except ValueError as exc:
        await goals_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
