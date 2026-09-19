"""Personal investment routes — /api/personal/investments (Plan 04)."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.db_dependencies import PGSessionDep as SessionDep
from app.api.routes.investments.investment_routes import _resp, _service
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
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import SplitLine
from app.api.routes.investments.investment_service import contribute, redeem

router = APIRouter(prefix="/personal/investments", tags=["personal-investments"])


@router.get("", response_model=InvestmentListResponse)
async def list_personal_investments(
    user: LoggedInUserDep,
    session: SessionDep,
    pagination: PaginationDep,
    status: str | None = None,
):
    svc = _service(session)
    items, _total, invested_total, current_total = await svc.list_personal_investments(
        user.id, pagination, status=status
    )
    return InvestmentListResponse(
        items=[_resp(i, True) for i in items],
        investedTotal=invested_total,
        currentValueTotal=current_total,
    )


@router.get("/history", response_model=InvestmentListResponse)
async def personal_investment_history(
    user: LoggedInUserDep,
    session: SessionDep,
    pagination: PaginationDep,
):
    svc = _service(session)
    items, _total, _, _ = await svc.list_personal_investments(user.id, pagination)
    history = [i for i in items if i.status in ("MATURED", "CLOSED", "CANCELLED")]
    return InvestmentListResponse(
        items=[_resp(i, True) for i in history],
        investedTotal=0,
        currentValueTotal=0,
    )


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    family_id: UUID,
    req: CreateInvestmentRequest,
):
    svc = _service(session)
    inv = await svc.create_personal_investment(user.id, family_id, req)
    return _resp(inv, True)


@router.get("/{investment_id}", response_model=InvestmentResponse)
async def get_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    return _resp(inv, True)


@router.patch("/{investment_id}", response_model=InvestmentResponse)
async def update_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
    req: UpdateInvestmentRequest,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    updated = await svc.update_investment(inv, req)
    return _resp(updated, True)


@router.delete("/{investment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    await svc.delete_investment(inv)


@router.post("/{investment_id}/contribute", response_model=InvestmentResponse)
async def contribute_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
    req: ContributeToInvestmentRequest,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    split_lines = None
    if req.splitLines:
        split_lines = [
            SplitLine(pool_type=s.poolType, family_id=s.familyId, amount=s.amount)
            for s in req.splitLines
        ]
    await contribute(session, inv, req.amount, split_lines, req.note, req.paidExternally)
    await session.commit()
    await session.refresh(inv)
    return _resp(inv, True)


@router.post("/{investment_id}/redeem", response_model=InvestmentResponse)
async def redeem_personal_investment(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
    req: RedeemInvestmentRequest,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    try:
        await redeem(
            session,
            inv,
            req.amount,
            req.note,
            credit_pool="PERSONAL",
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await session.commit()
    await session.refresh(inv)
    return _resp(inv, True)


@router.post("/{investment_id}/value", response_model=InvestmentResponse)
async def update_personal_investment_value(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
    req: UpdateInvestmentValueRequest,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    updated = await svc.update_value(inv, req.currentValue)
    return _resp(updated, True)


@router.get("/{investment_id}/txns", response_model=InvestmentTxnListResponse)
async def list_personal_investment_txns(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    txns = await svc.list_txns(inv)
    return InvestmentTxnListResponse(items=txns)


@router.post("/{investment_id}/split-plan", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_personal_investment_split_plan(
    user: LoggedInUserDep,
    session: SessionDep,
    investment_id: UUID,
    req: InvestmentSplitPlanRequest,
):
    svc = _service(session)
    inv = await svc.get_personal_investment(investment_id, user.id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    split_lines = [
        {"pool_type": s.poolType, "family_id": s.familyId, "amount": s.amount}
        for s in req.splitLines
    ]
    await svc.upsert_split_plan(inv, split_lines)
