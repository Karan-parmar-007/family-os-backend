import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.db_dependencies import PGSessionDep as SessionDep
from app.api.routes.investments.investment_schemas import (
    ContributeToInvestmentRequest,
    CreateInvestmentRequest,
    InvestmentListResponse,
    InvestmentResponse,
    InvestmentSplitPlanRequest,
    InvestmentTxnListResponse,
    RedeemInvestmentRequest,
    UpdateInvestmentRequest,
    UpdateInvestmentValueRequest,
)
from app.api.routes.investments.investment_service import (
    InvestmentService,
    contribute,
    redeem,
)
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import SplitLine
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/investments", tags=["investments"])


def _service(session: SessionDep) -> InvestmentService:
    return InvestmentService(session)


def _resp(inv, is_personal: bool) -> InvestmentResponse:
    data = inv.model_dump()
    data["is_personal"] = is_personal
    return InvestmentResponse.model_validate(data)


@router.get("", response_model=InvestmentListResponse)
async def list_investments(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    pagination: PaginationDep,
    family_id: UUID,
    status: str | None = None,
):
    svc = _service(session)
    scope_ctx = await load_scope_context(session, family_member.id, family_id)
    items, _total = await svc.list_investments(
        family_id, pagination, status=status, scope_ctx=scope_ctx
    )
    invested_total = sum((i.invested_amount for i, _ in items if i.status == "ACTIVE"), start=0)
    current_total = sum((i.current_value for i, _ in items if i.status == "ACTIVE"), start=0)
    return InvestmentListResponse(
        items=[_resp(i, p) for i, p in items],
        investedTotal=invested_total,
        currentValueTotal=current_total,
    )


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
async def create_investment(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    req: CreateInvestmentRequest,
):
    svc = _service(session)
    inv, is_personal = await svc.create_investment(family_id, family_member.id, req)
    return _resp(inv, is_personal)


@router.get("/history", response_model=InvestmentListResponse)
async def investment_history(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    pagination: PaginationDep,
    family_id: UUID,
):
    svc = _service(session)
    scope_ctx = await load_scope_context(session, family_member.id, family_id)
    items, _total = await svc.list_investments(family_id, pagination, scope_ctx=scope_ctx)
    items = [(i, p) for i, p in items if i.status in ("MATURED", "CLOSED", "CANCELLED")]
    return InvestmentListResponse(
        items=[_resp(i, p) for i, p in items],
        investedTotal=0,
        currentValueTotal=0,
    )


@router.get("/{investment_id}", response_model=InvestmentResponse)
async def get_investment(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_visible(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _resp(inv, is_personal)


@router.patch("/{investment_id}", response_model=InvestmentResponse)
async def update_investment(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
    req: UpdateInvestmentRequest,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await svc.update_investment(inv, req)
    return _resp(updated, is_personal)


@router.delete("/{investment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investment(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await svc.delete_investment(inv)


@router.post("/{investment_id}/contribute", response_model=InvestmentResponse)
async def contribute_to_investment_route(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
    req: ContributeToInvestmentRequest,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    split_lines = None
    if req.splitLines:
        split_lines = [
            SplitLine(pool_type=s.poolType, family_id=s.familyId, amount=s.amount)
            for s in req.splitLines
        ]
    await contribute(session, inv, req.amount, split_lines, req.note, req.paidExternally)
    await session.commit()
    await session.refresh(inv)
    return _resp(inv, is_personal)


@router.post("/{investment_id}/redeem", response_model=InvestmentResponse)
async def redeem_investment_route(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
    req: RedeemInvestmentRequest,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        await redeem(session, inv, req.amount, req.note, credit_pool=req.creditPool, user_id=family_member.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await session.commit()
    await session.refresh(inv)
    return _resp(inv, is_personal)


@router.post("/{investment_id}/value", response_model=InvestmentResponse)
async def update_investment_value(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
    req: UpdateInvestmentValueRequest,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await svc.update_value(inv, req.currentValue)
    return _resp(updated, is_personal)


@router.get("/{investment_id}/txns", response_model=InvestmentTxnListResponse)
async def list_investment_txns(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_visible(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    txns = await svc.list_txns(inv)
    return InvestmentTxnListResponse(items=txns)


@router.post("/{investment_id}/split-plan", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_investment_split_plan(
    family_member: LoggedInFamilyMemberDep,
    session: SessionDep,
    family_id: UUID,
    investment_id: UUID,
    req: InvestmentSplitPlanRequest,
):
    svc = _service(session)
    found = await svc.get_investment(investment_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    inv, is_personal = found
    try:
        await require_entity_editable(session, family_member.id, family_id, inv, is_personal=is_personal)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    split_lines = [
        {"pool_type": s.poolType, "family_id": s.familyId, "amount": s.amount}
        for s in req.splitLines
    ]
    await svc.upsert_split_plan(inv, split_lines)
