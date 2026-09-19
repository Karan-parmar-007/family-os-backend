"""Personal debt routes — /api/personal/debts (Plan 02)."""
import logging
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import DebtServiceDep
from app.api.routes.debt.debt_routes import _debt_response
from app.api.routes.debt.debt_schemas import (
    DebtCreateRequest,
    DebtListResponse,
    DebtResponse,
    DebtUpdateRequest,
    DefaultListResponse,
    DefaultSettleRequest,
    DefaultWaiveRequest,
    PartPaymentRequest,
    PartPaymentResponse,
    PartPaymentSimulateResponse,
    PaymentAllocationResponse,
    PaymentEventListResponse,
    PaymentEventResponse,
    ScopeViewItem,
    ScopeViewListResponse,
    ScopeViewUpsertRequest,
    SplitPlanRequest,
    ContributionRequest,
    ContributionResponse,
)
from app.api.routes.debt.debt_service import (
    require_debt_owner,
    resolve_debt,
    simulate_part_payment,
)
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import InsufficientFundsError, SplitLine, SplitValidationError


def _insufficient_funds_detail(exc: InsufficientFundsError) -> str:
    return (
        f"Insufficient funds: available {exc.available}, required {exc.required}. "
        "Add money to your savings (or lower the amount) and try again."
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/personal/debts", tags=["personal-debt"])


@router.get("", response_model=DebtListResponse)
async def list_personal_debts(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    pagination: PaginationDep,
    status: str | None = "ACTIVE",
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
    has_emi: bool | None = Query(default=None, alias="hasEmi"),
) -> DebtListResponse:
    items, total = await debt_service.list_personal_debts(
        user.id,
        pagination,
        status=status,
        q=q,
        type=type,
        has_emi=has_emi,
    )
    return DebtListResponse.from_page(
        [_debt_response(d, True, user.id) for d in items],
        total=total,
        pagination=pagination,
    )


@router.get("/history", response_model=DebtListResponse)
async def personal_debt_history(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    pagination: PaginationDep,
) -> DebtListResponse:
    items, total = await debt_service.list_personal_debts(
        user.id, pagination, status="PAID"
    )
    return DebtListResponse.from_page(
        [_debt_response(d, True, user.id) for d in items],
        total=total,
        pagination=pagination,
    )


@router.post("", response_model=DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_debt(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: DebtCreateRequest,
    family_id: UUID,
) -> DebtResponse:
    try:
        debt = await debt_service.create_personal_debt(user.id, family_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _debt_response(debt, True, user.id)


@router.get("/{debt_id}", response_model=DebtResponse)
async def get_personal_debt(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
) -> DebtResponse:
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    return _debt_response(debt, True, user.id)


@router.patch("/{debt_id}", response_model=DebtResponse)
async def update_personal_debt(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
    request: DebtUpdateRequest,
) -> DebtResponse:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await debt_service.update_debt(canonical, request)
    refreshed = await debt_service.get_personal_debt(debt_id, user.id)
    if refreshed:
        return _debt_response(refreshed, True, user.id)
    return _debt_response(canonical, True, user.id)


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_debt(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
) -> None:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await debt_service.delete_debt(canonical)


@router.post("/{debt_id}/part-payment", response_model=PartPaymentResponse)
async def personal_part_payment(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: PartPaymentRequest,
    debt_id: UUID,
) -> PartPaymentResponse:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        split_lines = None
        if request.splitLines:
            split_lines = [
                SplitLine(
                    pool_type=s.poolType,
                    family_id=s.familyId,
                    amount=s.amount,
                    user_id=(
                        (
                            getattr(s, "userId", None)
                            or getattr(s, "user_id", None)
                            or user.id
                        )
                        if s.poolType == "PERSONAL"
                        else None
                    ),
                )
                for s in request.splitLines
            ]
        reassignments = None
        if request.reassignments is not None:
            reassignments = [
                {
                    "poolType": r.poolType,
                    "familyId": r.familyId,
                    "userId": r.userId,
                    "amount": r.amount,
                    "expectedTotal": r.expectedTotal,
                    "obligationRemaining": r.obligationRemaining,
                }
                for r in request.reassignments
            ]
        res = await debt_service.part_payment(
            canonical,
            request.amount,
            request.mode,
            split_lines=split_lines,
            paid_externally=request.paidExternally,
            target_emi=request.targetEmi,
            target_tenure=request.targetTenure,
            use_balance=request.useBalance,
            reassignments=reassignments,
            actor_user_id=user.id,
        )
        return PartPaymentResponse(
            oldRemaining=res["old_remaining"],
            newRemaining=res["new_remaining"],
            oldEmi=res["old_emi"],
            newEmi=res["new_emi"],
            newPeriods=res["new_periods"],
            note=res["note"],
            interestSavedEstimate=res.get("interest_saved_estimate"),
            payoffDate=res.get("payoff_date"),
            periodsCleared=res.get("periods_cleared") or 0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SplitValidationError as exc:
        await debt_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InsufficientFundsError as exc:
        await debt_service.pg_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_insufficient_funds_detail(exc),
        )


@router.post("/{debt_id}/contributions", response_model=ContributionResponse)
async def personal_contribute_to_balance(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: ContributionRequest,
    debt_id: UUID,
) -> ContributionResponse:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        res = await debt_service.contribute_to_balance(
            canonical,
            actor_user_id=user.id,
            amount=request.amount,
            pool_type=request.poolType,
            family_id=request.familyId,
            user_id=request.userId,
        )
        return ContributionResponse(
            amount=res["amount"],
            balanceForPartPayment=res["balance_for_part_payment"],
            obligationRemaining=res.get("obligation_remaining"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InsufficientFundsError as exc:
        await debt_service.pg_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_insufficient_funds_detail(exc),
        )


@router.post("/{debt_id}/part-payment/simulate", response_model=PartPaymentSimulateResponse)
async def personal_simulate_part_payment(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: PartPaymentRequest,
    debt_id: UUID,
) -> PartPaymentSimulateResponse:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        res = simulate_part_payment(
            canonical,
            amount=request.amount,
            mode=request.mode,
            target_emi=request.targetEmi,
            target_tenure=request.targetTenure,
        )
        return PartPaymentSimulateResponse(
            oldRemaining=res["old_remaining"],
            newRemaining=res["new_remaining"],
            oldEmi=res["old_emi"],
            newEmi=res["new_emi"],
            newPeriods=res["new_periods"],
            note=res["note"],
            interestSavedEstimate=res.get("interest_saved_estimate") or Decimal("0"),
            payoffDate=res.get("payoff_date"),
            periodsCleared=res.get("periods_cleared") or 0,
            emiNextDate=res.get("emi_next_date"),
            endDate=res.get("end_date"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{debt_id}/split-plan", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_personal_split_plan(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
    request: SplitPlanRequest,
) -> None:
    row = await debt_service.get_personal_debt(debt_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        await debt_service.upsert_split_plan(
            canonical,
            [
                {
                    "pool_type": sl.poolType,
                    "family_id": sl.familyId,
                    "amount": sl.amount,
                    "expected_total": getattr(sl, "expectedTotal", None),
                    "obligation_remaining": getattr(sl, "obligationRemaining", None),
                    **(
                        {
                            "user_id": (
                                getattr(sl, "userId", None)
                                or getattr(sl, "user_id", None)
                                or user.id
                            )
                        }
                        if sl.poolType == "PERSONAL"
                        else {}
                    ),
                }
                for sl in request.splitLines
            ],
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{debt_id}/payment-events", response_model=PaymentEventListResponse)
async def list_personal_payment_events(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
) -> PaymentEventListResponse:
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    events = await debt_service.list_payment_events(debt_id)
    return PaymentEventListResponse(
        items=[
            PaymentEventResponse(
                id=e.id,
                debtId=e.debt_id,
                eventType=e.event_type,
                periodKey=e.period_key,
                scheduledAmount=e.scheduled_amount,
                actualAmount=e.actual_amount,
                principalAmount=e.principal_amount,
                interestAmount=e.interest_amount,
                feeAmount=e.fee_amount,
                paidAt=e.paid_at,
                status=e.status,
                paidExternally=e.paid_externally,
                note=e.note,
                jobId=e.job_id,
                partPaymentMode=e.part_payment_mode,
                underpaymentPolicy=e.underpayment_policy,
                overpaymentPolicy=e.overpayment_policy,
                createdAt=e.created_at,
                allocations=[
                    PaymentAllocationResponse(
                        poolType=a.pool_type,
                        familyId=a.family_id,
                        userId=a.user_id,
                        amount=a.amount,
                    )
                    for a in getattr(e, "_allocations", [])
                ],
            )
            for e in events
        ]
    )


@router.get("/{debt_id}/scope-views", response_model=ScopeViewListResponse)
async def get_personal_scope_views(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
) -> ScopeViewListResponse:
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    views = await debt_service.list_scope_views(debt_id)
    return ScopeViewListResponse(
        items=[
            ScopeViewItem(
                id=v.id,
                scope_kind=v.scope_kind,
                family_id=v.family_id,
                user_id=v.user_id,
                is_primary=v.is_primary,
                display_name=v.display_name,
                display_type=v.display_type,
                display_total_amount=v.display_total_amount,
                display_remaining_amount=v.display_remaining_amount,
                display_emi_amount=v.display_emi_amount,
                display_interest_rate=v.display_interest_rate,
                is_masked=v.is_masked,
                show_breakdown=v.show_breakdown,
                access_level=v.access_level,
            )
            for v in views
        ]
    )


@router.put("/{debt_id}/scope-views", response_model=ScopeViewListResponse)
async def put_personal_scope_views(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: ScopeViewUpsertRequest,
    debt_id: UUID,
) -> ScopeViewListResponse:
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(user.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        views = await debt_service.upsert_scope_views(
            debt_id,
            user.id,
            [
                {
                    "scope_kind": v.scope_kind,
                    "family_id": v.family_id,
                    "user_id": v.user_id,
                    "display_name": v.display_name,
                    "display_type": v.display_type,
                    "display_total_amount": v.display_total_amount,
                    "display_remaining_amount": v.display_remaining_amount,
                    "display_emi_amount": v.display_emi_amount,
                    "display_interest_rate": v.display_interest_rate,
                    "is_masked": v.is_masked,
                    "show_breakdown": v.show_breakdown,
                    "access_level": v.access_level,
                }
                for v in request.resolved_views()
            ],
        )
        return ScopeViewListResponse(
            items=[
                ScopeViewItem(
                    id=v.id,
                    scope_kind=v.scope_kind,
                    family_id=v.family_id,
                    user_id=v.user_id,
                    is_primary=v.is_primary,
                    display_name=v.display_name,
                    display_type=v.display_type,
                    display_total_amount=v.display_total_amount,
                    display_remaining_amount=v.display_remaining_amount,
                    display_emi_amount=v.display_emi_amount,
                    display_interest_rate=v.display_interest_rate,
                    is_masked=v.is_masked,
                    show_breakdown=v.show_breakdown,
                    access_level=v.access_level,
                )
                for v in views
            ]
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{debt_id}/defaults", response_model=DefaultListResponse)
async def list_personal_defaults(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    debt_id: UUID,
) -> DefaultListResponse:
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    items, total_open = await debt_service.list_defaults(debt, True)
    return DefaultListResponse(
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


@router.post("/{debt_id}/defaults/{default_id}/settle")
async def settle_personal_default(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: DefaultSettleRequest,
    debt_id: UUID,
    default_id: UUID,
):
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        split_lines = (
            [
                {
                    "pool_type": ln.poolType,
                    "family_id": ln.familyId,
                    "amount": ln.amount,
                    **(
                        {
                            "user_id": (
                                getattr(ln, "userId", None)
                                or getattr(ln, "user_id", None)
                                or user.id
                            )
                        }
                        if ln.poolType == "PERSONAL"
                        else {}
                    ),
                }
                for ln in request.splitLines
            ]
            if request.splitLines
            else None
        )
        await debt_service.settle_default(default_id, split_lines=split_lines, note=request.note)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{debt_id}/defaults/{default_id}/waive")
async def waive_personal_default(
    user: LoggedInUserDep,
    debt_service: DebtServiceDep,
    request: DefaultWaiveRequest,
    debt_id: UUID,
    default_id: UUID,
):
    debt = await debt_service.get_personal_debt(debt_id, user.id)
    if debt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        await debt_service.waive_default(default_id, note=request.note)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
