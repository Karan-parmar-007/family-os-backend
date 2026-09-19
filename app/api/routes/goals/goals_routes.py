from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import GoalsServiceDep
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
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible

router = APIRouter(prefix="/families/{family_id}/goals", tags=["goals"])


def _resp(goal, is_personal: bool) -> GoalResponse:
    data = goal.model_dump()
    data["is_personal"] = is_personal
    return GoalResponse.model_validate(data)


@router.get("", response_model=GoalListResponse)
async def list_goals(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
    status: str | None = Query(default="ACTIVE"),
) -> GoalListResponse:
    scope_ctx = await load_scope_context(
        goals_service.pg_session, family_member.id, family_id
    )
    items, total = await goals_service.list_goals(
        family_id, pagination, scope_ctx=scope_ctx, status=status
    )
    return GoalListResponse.from_page(
        [_resp(g, p) for g, p in items], total=total, pagination=pagination
    )


@router.get("/history", response_model=GoalListResponse)
async def goal_history(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> GoalListResponse:
    scope_ctx = await load_scope_context(
        goals_service.pg_session, family_member.id, family_id
    )
    items, total = await goals_service.list_history(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return GoalListResponse.from_page(
        [_resp(g, p) for g, p in items], total=total, pagination=pagination
    )


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    request: GoalCreateRequest,
    family_id: UUID,
) -> GoalResponse:
    goal, is_personal = await goals_service.create_goal(
        family_id, family_member.id, request
    )
    return _resp(goal, is_personal)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    family_id: UUID,
    goal_id: UUID,
) -> GoalResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_visible(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _resp(goal, is_personal)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    request: GoalUpdateRequest,
    family_id: UUID,
    goal_id: UUID,
) -> GoalResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_editable(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await goals_service.update_goal(goal, request)
    return _resp(updated, found[1])


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    family_id: UUID,
    goal_id: UUID,
) -> None:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_editable(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await goals_service.delete_goal(goal, is_personal, family_member.id)


@router.get("/{goal_id}/contributions", response_model=GoalContributionListResponse)
async def list_goal_contributions(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    family_id: UUID,
    goal_id: UUID,
) -> GoalContributionListResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_visible(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    items = await goals_service.list_contributions(goal_id, family_id, is_personal)
    return GoalContributionListResponse(
        items=[GoalContributionResponse.model_validate(i) for i in items]
    )


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_goal_contribution(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    request: GoalContributionCreateRequest,
    family_id: UUID,
    goal_id: UUID,
) -> GoalContributionResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_visible(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if is_personal and goal.user_id != family_member.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your goal")
    try:
        contrib = await goals_service.add_contribution(
            goal, is_personal, family_member.id, request
        )
        return GoalContributionResponse.model_validate(contrib)
    except ValueError as exc:
        await goals_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{goal_id}/withdraw",
    response_model=GoalContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def withdraw_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    request: GoalWithdrawRequest,
    family_id: UUID,
    goal_id: UUID,
) -> GoalContributionResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_editable(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if is_personal and goal.user_id != family_member.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your goal")
    try:
        contrib = await goals_service.withdraw(goal, is_personal, family_member.id, request)
        return GoalContributionResponse.model_validate(contrib)
    except ValueError as exc:
        await goals_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{goal_id}/achieve", response_model=GoalResponse)
async def achieve_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    family_id: UUID,
    goal_id: UUID,
) -> GoalResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_editable(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        
    goal.status = "ACHIEVED"
    from datetime import datetime, timezone
    goal.completed_at = datetime.now(timezone.utc)
    await goals_service.pg_session.commit()
    await goals_service.pg_session.refresh(goal)
    return _resp(goal, is_personal)


@router.post("/{goal_id}/release", response_model=GoalResponse)
async def release_goal(
    family_member: LoggedInFamilyMemberDep,
    goals_service: GoalsServiceDep,
    family_id: UUID,
    goal_id: UUID,
) -> GoalResponse:
    found = await goals_service.get_goal(goal_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    goal, is_personal = found
    try:
        await require_entity_editable(
            goals_service.pg_session, family_member.id, family_id, goal, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        
    try:
        await goals_service.release_achieved_goal(goal, is_personal, family_member.id)
        # release_achieved_goal just credits pool and sets collected_amount = 0
        # We can also update the status to CLOSED or RELEASED if desired, but we'll leave it as ACHIEVED
        await goals_service.pg_session.refresh(goal)
        return _resp(goal, is_personal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
