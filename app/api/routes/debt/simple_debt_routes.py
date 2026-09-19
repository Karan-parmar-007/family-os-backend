import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.debt.simple_debt_schemas import (
    DebtCreateRequest,
    DebtUpdateRequest,
    DebtResponse,
    DebtListResponse,
)
from app.api.routes.debt.simple_debt_service import SimpleDebtService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debts", tags=["debts"])


def get_debt_service(session: PGSessionDep) -> SimpleDebtService:
    return SimpleDebtService(session)


def _format_debt(d) -> DebtResponse:
    amt = float(d.amount)
    paid = float(d.amount_paid)
    remaining = max(0.0, amt - paid)
    return DebtResponse(
        id=d.id,
        scope=d.scope,
        family_id=d.family_id,
        owner_type=d.owner_type,
        owner_user_id=d.owner_user_id,
        name=d.name,
        amount=amt,
        amount_paid=paid,
        remaining_amount=remaining,
        has_emi=d.has_emi,
        add_emi_to_paid=d.add_emi_to_paid,
        linked_rule_id=d.linked_rule_id,
        document_id=d.document_id,
        let_everyone_edit=d.let_everyone_edit,
        created_by=d.created_by,
        status=d.status,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.post("", response_model=DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_debt(
    request: DebtCreateRequest,
    current_user: CurrentUserDep,
    service: SimpleDebtService = Depends(get_debt_service),
) -> DebtResponse:
    debt = await service.create_debt(current_user.id, request)
    return _format_debt(debt)


@router.get("", response_model=DebtListResponse)
async def list_debts(
    current_user: CurrentUserDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None),
    service: SimpleDebtService = Depends(get_debt_service),
) -> DebtListResponse:
    items, total = await service.list_debts(current_user.id, scope=scope, family_id=family_id, status_filter=status)
    return DebtListResponse(items=[_format_debt(d) for d in items], total=total)


@router.patch("/{debt_id}", response_model=DebtResponse)
async def update_debt(
    debt_id: UUID,
    request: DebtUpdateRequest,
    current_user: CurrentUserDep,
    service: SimpleDebtService = Depends(get_debt_service),
) -> DebtResponse:
    debt = await service.update_debt(current_user.id, debt_id, request)
    return _format_debt(debt)


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(
    debt_id: UUID,
    current_user: CurrentUserDep,
    service: SimpleDebtService = Depends(get_debt_service),
):
    await service.delete_debt(current_user.id, debt_id)
