import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import DebtServiceDep, TransferServiceDep
from app.api.routes.debt.debt_schemas import (
    DebtCreateRequest,
    DebtListResponse,
    DebtQuoteRequest,
    DebtResponse,
    DebtUpdateRequest,
    DefaultListResponse,
    DefaultSettleRequest,
    DefaultWaiveRequest,
    PartPaymentRequest,
    PartPaymentResponse,
    PartPaymentSimulateResponse,
    PaymentEventListResponse,
    PaymentEventResponse,
    PaymentAllocationResponse,
    ScopeViewItem,
    ScopeViewListResponse,
    ScopeViewUpsertRequest,
    SplitPlanRequest,
    ContributionRequest,
    ContributionResponse,
)
from app.api.routes.debt.debt_service import require_debt_owner, resolve_debt
from app.api.routes.transfer.transfer_schemas import TransferCreateRequest, TransferResponse
from app.api.schemas.pagination import PaginationDep
from app.core.funding_service import (
    InsufficientFundsError,
    SplitLine,
    SplitValidationError,
)
from app.core.interest_math import quote
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible
from app.config import feature_settings
from decimal import Decimal


def _insufficient_funds_detail(exc: InsufficientFundsError) -> str:
    return (
        f"Insufficient funds: available {exc.available}, required {exc.required}. "
        "Add money to your savings (or lower the amount) and try again."
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/debts", tags=["debt"])


def _debt_response(debt, is_personal: bool, viewer_user_id: UUID | None = None) -> DebtResponse:
    data = debt.model_dump() if hasattr(debt, "model_dump") else dict(debt)
    data["is_personal"] = is_personal
    owner_id = getattr(debt, "debt_in_the_name_of", None) or getattr(debt, "user_id", None)
    if is_personal:
        data["debt_in_the_name_of"] = getattr(debt, "user_id", None) or owner_id
    else:
        data["debt_in_the_name_of"] = owner_id
    if getattr(debt, "is_masked", False) and debt.is_masked:
        if viewer_user_id and viewer_user_id == owner_id:
            data["real"] = {
                "totalAmount": getattr(debt, "real_total_amount", None),
                "remainingAmount": getattr(debt, "real_remaining_amount", None),
                "emiAmount": getattr(debt, "real_emi_amount", None),
                "interestRate": getattr(debt, "real_interest_rate", None),
            }
    # Optional presentation fields (DebtRow)
    if "show_breakdown" not in data and hasattr(debt, "show_breakdown"):
        data["show_breakdown"] = debt.show_breakdown
    if "view_id" not in data and hasattr(debt, "view_id"):
        data["view_id"] = debt.view_id
    if "scope_views" not in data and hasattr(debt, "scope_views"):
        data["scope_views"] = debt.scope_views
    if "balance_for_part_payment" not in data and hasattr(debt, "balance_for_part_payment"):
        data["balance_for_part_payment"] = debt.balance_for_part_payment
    if "split_lines" not in data and hasattr(debt, "split_lines"):
        data["split_lines"] = debt.split_lines
    for key in (
        "my_emi_amount",
        "my_obligation_remaining",
        "my_expected_total",
        "can_contribute",
        "is_owner",
        "can_part_payment",
    ):
        if key not in data and hasattr(debt, key):
            data[key] = getattr(debt, key)
    return DebtResponse.model_validate(data)


@router.get("/history", response_model=DebtListResponse)
async def debt_history(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> DebtListResponse:
    scope_ctx = await load_scope_context(
        debt_service.pg_session, family_member.id, family_id
    )
    items, total = await debt_service.list_debt_history(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return DebtListResponse.from_page(
        [_debt_response(d, is_personal, family_member.id) for d, is_personal in items],
        total=total,
        pagination=pagination,
    )


@router.get("", response_model=DebtListResponse)
async def list_debts(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
    status: str | None = Query(default="ACTIVE"),
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
    owner_user_id: UUID | None = Query(default=None, alias="ownerUserId"),
    has_emi: bool | None = Query(default=None, alias="hasEmi"),
    is_masked: bool | None = Query(default=None, alias="isMasked"),
) -> DebtListResponse:
    scope_ctx = await load_scope_context(
        debt_service.pg_session, family_member.id, family_id
    )
    items, total = await debt_service.list_debts(
        family_id,
        pagination,
        scope_ctx=scope_ctx,
        status=status,
        q=q,
        type=type,
        owner_user_id=owner_user_id,
        has_emi=has_emi,
        is_masked=is_masked,
    )
    return DebtListResponse.from_page(
        [_debt_response(d, is_personal, family_member.id) for d, is_personal in items],
        total=total,
        pagination=pagination,
    )


@router.post("", response_model=DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_debt(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: DebtCreateRequest,
    family_id: UUID,
) -> DebtResponse:
    try:
        debt, is_personal = await debt_service.create_debt(
            family_id, family_member.id, request
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _debt_response(debt, is_personal, family_member.id)


@router.post("/quote", response_model=dict)
async def quote_debt(
    family_member: LoggedInFamilyMemberDep,
    request: DebtQuoteRequest,
) -> dict:
    del family_member
    try:
        return quote(
            principal=request.principal,
            interest_type=request.interest_type,
            annual_rate_pct=request.annual_rate_pct or 0.0,
            compounding_frequency=request.compounding_frequency,
            emi_amount=request.emi_amount,
            tenure_months=request.tenure_months,
            fixed_fee_amount=request.fixed_fee_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{debt_id}", response_model=DebtResponse)
async def get_debt(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    family_id: UUID,
    debt_id: UUID,
) -> DebtResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, is_personal = found
    try:
        await require_entity_visible(
            debt_service.pg_session, family_member.id, family_id, debt, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _debt_response(debt, is_personal, family_member.id)


@router.patch("/{debt_id}", response_model=DebtResponse)
async def update_debt(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: DebtUpdateRequest,
    family_id: UUID,
    debt_id: UUID,
) -> DebtResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    _, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(family_member.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await debt_service.update_debt(canonical, request)
    refreshed = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if refreshed:
        return _debt_response(refreshed[0], refreshed[1], family_member.id)
    return _debt_response(updated, is_personal, family_member.id)


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    family_id: UUID,
    debt_id: UUID,
) -> None:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(family_member.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await debt_service.delete_debt(canonical)


@router.post("/{debt_id}/split-plan", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_debt_split_plan(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: SplitPlanRequest,
    family_id: UUID,
    debt_id: UUID,
) -> None:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    _, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(family_member.id, canonical)
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
                                or family_member.id
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


@router.post("/{debt_id}/transfer", response_model=TransferResponse)
async def transfer_debt(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    transfer_service: TransferServiceDep,
    request: TransferCreateRequest,
    family_id: UUID,
    debt_id: UUID,
) -> TransferResponse:
    if not feature_settings.FEATURE_TRANSFERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, _ = found
    transfer_req = TransferCreateRequest(
        from_scope=request.from_scope,
        to_scope=request.to_scope,
        from_user_id=request.from_user_id,
        to_user_id=request.to_user_id,
        entity_type="DEBT",
        amount=debt.remaining_amount,
        source_entity_id=debt_id,
        transfer_logs=request.transfer_logs,
        transfer_docs=request.transfer_docs,
    )
    try:
        transfer = await transfer_service.create_transfer(
            family_id, family_member.id, transfer_req
        )
        await debt_service.pg_session.commit()
        return TransferResponse.model_validate(transfer)
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{debt_id}/part-payment", response_model=PartPaymentResponse)
async def part_payment(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: PartPaymentRequest,
    family_id: UUID,
    debt_id: UUID,
) -> PartPaymentResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    _, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")

    try:
        require_debt_owner(family_member.id, canonical)
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
                            or family_member.id
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
            actor_user_id=family_member.id,
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
async def contribute_to_debt_balance(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: ContributionRequest,
    family_id: UUID,
    debt_id: UUID,
) -> ContributionResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        res = await debt_service.contribute_to_balance(
            canonical,
            actor_user_id=family_member.id,
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


@router.get("/{debt_id}/defaults", response_model=DefaultListResponse)
async def list_debt_defaults(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    family_id: UUID,
    debt_id: UUID,
) -> DefaultListResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, is_personal = found
    try:
        await require_entity_visible(
            debt_service.pg_session, family_member.id, family_id, debt, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    items, total_open = await debt_service.list_defaults(debt, is_personal)
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


@router.post("/{debt_id}/defaults/{default_id}/settle", response_model=dict)
async def settle_debt_default(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: DefaultSettleRequest,
    family_id: UUID,
    debt_id: UUID,
    default_id: UUID,
):
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt_row, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        await require_entity_editable(
            debt_service.pg_session, family_member.id, family_id, debt_row, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

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
                                or family_member.id
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


@router.post("/{debt_id}/defaults/{default_id}/waive", response_model=dict)
async def waive_debt_default(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: DefaultWaiveRequest,
    family_id: UUID,
    debt_id: UUID,
    default_id: UUID,
):
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt_row, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        await require_entity_editable(
            debt_service.pg_session, family_member.id, family_id, debt_row, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    try:
        await debt_service.waive_default(default_id, note=request.note)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{debt_id}/part-payment/simulate", response_model=PartPaymentSimulateResponse)
async def simulate_part_payment(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: PartPaymentRequest,
    family_id: UUID,
    debt_id: UUID,
) -> PartPaymentSimulateResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, is_personal = found
    try:
        await require_entity_visible(
            debt_service.pg_session, family_member.id, family_id, debt, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(family_member.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        from app.api.routes.debt.debt_service import simulate_part_payment as _simulate

        res = _simulate(
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


@router.get("/{debt_id}/payment-events", response_model=PaymentEventListResponse)
async def list_payment_events(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    family_id: UUID,
    debt_id: UUID,
) -> PaymentEventListResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, is_personal = found
    try:
        await require_entity_visible(
            debt_service.pg_session, family_member.id, family_id, debt, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
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
async def get_scope_views(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    family_id: UUID,
    debt_id: UUID,
) -> ScopeViewListResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    debt, is_personal = found
    try:
        await require_entity_visible(
            debt_service.pg_session, family_member.id, family_id, debt, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
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
async def put_scope_views(
    family_member: LoggedInFamilyMemberDep,
    debt_service: DebtServiceDep,
    request: ScopeViewUpsertRequest,
    family_id: UUID,
    debt_id: UUID,
) -> ScopeViewListResponse:
    found = await debt_service.get_debt(
        debt_id, family_id, viewer_user_id=family_member.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    _, is_personal = found
    canonical = await resolve_debt(debt_service.pg_session, debt_id)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Debt not found")
    try:
        require_debt_owner(family_member.id, canonical)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    try:
        views = await debt_service.upsert_scope_views(
            debt_id,
            family_member.id,
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

