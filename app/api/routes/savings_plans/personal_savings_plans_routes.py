from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import SavingsPlansServiceDep
from app.api.routes.savings_plans.savings_plans_routes import _resp
from app.api.routes.savings_plans.savings_plans_schemas import (
    SavingsPlanContributionCreateRequest,
    SavingsPlanContributionListResponse,
    SavingsPlanContributionResponse,
    SavingsPlanCreateRequest,
    SavingsPlanDefaultListResponse,
    SavingsPlanDefaultSettleRequest,
    SavingsPlanDefaultWaiveRequest,
    SavingsPlanListResponse,
    SavingsPlanPartPaymentRequest,
    SavingsPlanPayoutRequest,
    SavingsPlanResponse,
    SavingsPlanUpdateRequest,
    LinkCandidateListResponse,
    LinkCandidateResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import SplitLine

router = APIRouter(prefix="/personal/savings-plans", tags=["personal-savings-plans"])


@router.get("", response_model=SavingsPlanListResponse)
async def list_personal_savings_plans(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    pagination: PaginationDep,
    status: str | None = Query(default="ACTIVE"),
) -> SavingsPlanListResponse:
    items, total = await savings_plans_service.list_personal_plans(
        user.id, pagination, status=status
    )
    return SavingsPlanListResponse.from_page(
        [_resp(p, True) for p in items], total=total, pagination=pagination
    )


@router.get("/history", response_model=SavingsPlanListResponse)
async def personal_savings_plan_history(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    pagination: PaginationDep,
) -> SavingsPlanListResponse:
    items, total = await savings_plans_service.list_personal_plans(
        user.id, pagination, status=None
    )
    history = [p for p in items if p.status in ("COMPLETED", "CANCELLED")]
    return SavingsPlanListResponse.from_page(
        [_resp(p, True) for p in history], total=len(history), pagination=pagination
    )


@router.get("/link-candidates", response_model=LinkCandidateListResponse)
async def personal_link_candidates(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    purpose_type: str,
) -> LinkCandidateListResponse:
    items = await savings_plans_service.link_candidates(
        family_id, purpose_type, user_id=user.id
    )
    return LinkCandidateListResponse(
        items=[LinkCandidateResponse.model_validate(i) for i in items]
    )


@router.post("", response_model=SavingsPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_savings_plan(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanCreateRequest,
    family_id: UUID,
) -> SavingsPlanResponse:
    plan = await savings_plans_service.create_personal_plan(user.id, family_id, request)
    return _resp(plan, True)


@router.get("/{plan_id}", response_model=SavingsPlanResponse)
async def get_personal_savings_plan(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
) -> SavingsPlanResponse:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _resp(plan, True)


@router.patch("/{plan_id}", response_model=SavingsPlanResponse)
async def update_personal_savings_plan(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
    request: SavingsPlanUpdateRequest,
) -> SavingsPlanResponse:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    updated = await savings_plans_service.update_plan(plan, request)
    return _resp(updated, True)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_savings_plan(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
) -> None:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await savings_plans_service.delete_plan(plan)


@router.post("/{plan_id}/part-payment", response_model=SavingsPlanResponse)
async def personal_part_payment(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
    request: SavingsPlanPartPaymentRequest,
) -> SavingsPlanResponse:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    split_lines = None
    if request.splitLines:
        split_lines = [
            SplitLine(pool_type=s.poolType, family_id=s.familyId, amount=s.amount)
            for s in request.splitLines
        ]
    try:
        updated = await savings_plans_service.part_payment(
            plan,
            amount=request.amount,
            mode=request.mode,
            split_lines=split_lines,
            paid_externally=request.paidExternally,
        )
        return _resp(updated, True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{plan_id}/payout", response_model=SavingsPlanResponse)
async def personal_payout(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
    request: SavingsPlanPayoutRequest,
) -> SavingsPlanResponse:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        updated = await savings_plans_service.payout(
            plan, amount=request.amount, user_id=user.id, note=request.note
        )
        return _resp(updated, True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{plan_id}/defaults", response_model=SavingsPlanDefaultListResponse)
async def list_personal_defaults(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
) -> SavingsPlanDefaultListResponse:
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    items, total_open = await savings_plans_service.list_defaults(plan)
    return SavingsPlanDefaultListResponse(
        items=[
            {
                "id": i.id,
                "reason": i.reason,
                "amount": i.amount,
                "fineAmount": i.fine_amount,
                "status": i.status,
                "periodKey": i.period_key,
                "settledAt": i.settled_at,
                "createdAt": i.created_at,
            }
            for i in items
        ],
        totalOpen=total_open,
    )


@router.post("/{plan_id}/defaults/{default_id}/settle")
async def settle_personal_default(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
    default_id: UUID,
    request: SavingsPlanDefaultSettleRequest,
):
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    split_lines = (
        [
            {"pool_type": ln.poolType, "family_id": ln.familyId, "amount": ln.amount}
            for ln in request.splitLines
        ]
        if request.splitLines
        else None
    )
    try:
        await savings_plans_service.settle_default(
            default_id, split_lines=split_lines, note=request.note
        )
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{plan_id}/defaults/{default_id}/waive")
async def waive_personal_default(
    user: LoggedInUserDep,
    savings_plans_service: SavingsPlansServiceDep,
    plan_id: UUID,
    default_id: UUID,
    request: SavingsPlanDefaultWaiveRequest,
):
    plan = await savings_plans_service.get_personal_plan(plan_id, user.id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        await savings_plans_service.waive_default(default_id, note=request.note)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
