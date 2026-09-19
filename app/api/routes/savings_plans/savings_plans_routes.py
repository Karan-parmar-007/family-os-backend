from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import SavingsPlansServiceDep
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
    SavingsPlanPrepayRequest,
    SavingsPlanResponse,
    SavingsPlanUpdateRequest,
    LinkCandidateListResponse,
    LinkCandidateResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import SplitLine
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible

router = APIRouter(prefix="/families/{family_id}/savings-plans", tags=["savings-plans"])


def _resp(plan, is_personal: bool) -> SavingsPlanResponse:
    data = plan.model_dump()
    data["is_personal"] = is_personal
    return SavingsPlanResponse.model_validate(data)


@router.get("", response_model=SavingsPlanListResponse)
async def list_savings_plans(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> SavingsPlanListResponse:
    scope_ctx = await load_scope_context(
        savings_plans_service.pg_session, family_member.id, family_id
    )
    items, total = await savings_plans_service.list_plans(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return SavingsPlanListResponse.from_page(
        [_resp(p, pers) for p, pers in items], total=total, pagination=pagination
    )


@router.get("/history", response_model=SavingsPlanListResponse)
async def savings_plan_history(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> SavingsPlanListResponse:
    scope_ctx = await load_scope_context(
        savings_plans_service.pg_session, family_member.id, family_id
    )
    items, total = await savings_plans_service.list_plan_history(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return SavingsPlanListResponse.from_page(
        [_resp(p, pers) for p, pers in items], total=total, pagination=pagination
    )


@router.get("/link-candidates", response_model=LinkCandidateListResponse)
async def link_candidates(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    purpose_type: str,
) -> LinkCandidateListResponse:
    items = await savings_plans_service.link_candidates(
        family_id, purpose_type, user_id=family_member.id
    )
    return LinkCandidateListResponse(
        items=[LinkCandidateResponse.model_validate(i) for i in items]
    )


@router.post("", response_model=SavingsPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanCreateRequest,
    family_id: UUID,
) -> SavingsPlanResponse:
    plan, is_personal = await savings_plans_service.create_plan(
        family_id, family_member.id, request
    )
    return _resp(plan, is_personal)


@router.get("/{plan_id}", response_model=SavingsPlanResponse)
async def get_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_visible(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _resp(plan, is_personal)


@router.patch("/{plan_id}", response_model=SavingsPlanResponse)
async def update_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanUpdateRequest,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_editable(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await savings_plans_service.update_plan(plan, request)
    return _resp(updated, is_personal)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    plan_id: UUID,
) -> None:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_editable(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await savings_plans_service.delete_plan(plan)


@router.post("/{plan_id}/prepay", response_model=SavingsPlanResponse)
async def prepay_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanPrepayRequest,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_editable(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if is_personal and plan.user_id != family_member.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your plan")
    try:
        updated = await savings_plans_service.prepay_plan(
            plan,
            is_personal,
            family_member.id,
            request.amount,
            request.mode,
            request.contribution_date,
        )
        return _resp(updated, is_personal)
    except ValueError as exc:
        await savings_plans_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{plan_id}/contributions", response_model=SavingsPlanContributionListResponse)
async def list_savings_plan_contributions(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanContributionListResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_visible(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    items = await savings_plans_service.list_contributions(plan_id, family_id, is_personal)
    return SavingsPlanContributionListResponse(
        items=[SavingsPlanContributionResponse.model_validate(i) for i in items]
    )


@router.post(
    "/{plan_id}/contributions",
    response_model=SavingsPlanContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_savings_plan_contribution(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanContributionCreateRequest,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanContributionResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_visible(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if is_personal and plan.user_id != family_member.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your plan")
    try:
        contrib = await savings_plans_service.add_contribution(
            plan, is_personal, family_member.id, request
        )
        return SavingsPlanContributionResponse.model_validate(contrib)
    except ValueError as exc:
        await savings_plans_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{plan_id}/part-payment", response_model=SavingsPlanResponse)
async def part_payment_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanPartPaymentRequest,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_editable(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
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
        return _resp(updated, is_personal)
    except ValueError as exc:
        await savings_plans_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{plan_id}/payout", response_model=SavingsPlanResponse)
async def payout_savings_plan(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanPayoutRequest,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, is_personal = found
    try:
        await require_entity_editable(
            savings_plans_service.pg_session,
            family_member.id,
            family_id,
            plan,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        updated = await savings_plans_service.payout(
            plan, amount=request.amount, user_id=family_member.id, note=request.note
        )
        return _resp(updated, is_personal)
    except ValueError as exc:
        await savings_plans_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{plan_id}/defaults", response_model=SavingsPlanDefaultListResponse)
async def list_savings_plan_defaults(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    family_id: UUID,
    plan_id: UUID,
) -> SavingsPlanDefaultListResponse:
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    plan, _ = found
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
async def settle_savings_plan_default(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanDefaultSettleRequest,
    family_id: UUID,
    plan_id: UUID,
    default_id: UUID,
):
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
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
async def waive_savings_plan_default(
    family_member: LoggedInFamilyMemberDep,
    savings_plans_service: SavingsPlansServiceDep,
    request: SavingsPlanDefaultWaiveRequest,
    family_id: UUID,
    plan_id: UUID,
    default_id: UUID,
):
    found = await savings_plans_service.get_plan(plan_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        await savings_plans_service.waive_default(default_id, note=request.note)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
