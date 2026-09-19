"""User-scoped recurring income routes (personal management)."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.income_owner import LoggedInRecurringIncomeOwnerDep
from app.api.dependencies import IncomeServiceDep
from app.api.routes.family_income.income_schemas import (
    RecurringIncomeCreateRequest,
    RecurringIncomeMineListResponse,
    RecurringIncomeUpdateRequest,
    FamilyRecurringIncomeCreateResponse,
    FamilyRecurringIncomeUpdateResponse,
)
from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incomes/recurring", tags=["recurring-income"])


@router.get(
    "/mine",
    response_model=RecurringIncomeMineListResponse,
    status_code=status.HTTP_200_OK,
    summary="List current user's recurring incomes (full detail)",
)
async def list_my_recurring_incomes(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    pagination: PaginationDep,
    personal_only: bool = Query(
        default=True,
        description="When true (default), exclude family-page recurring incomes",
    ),
) -> RecurringIncomeMineListResponse:
    items, total_count = await income_service.list_user_recurring_incomes(
        user_id=current_user.id,
        pagination=pagination,
        personal_only=personal_only,
    )
    return RecurringIncomeMineListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.post(
    "",
    response_model=FamilyRecurringIncomeCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create recurring income with multi-family splits",
)
async def create_recurring_income(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    data: Annotated[RecurringIncomeCreateRequest, Depends(RecurringIncomeCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
) -> FamilyRecurringIncomeCreateResponse:
    try:
        income = await income_service.create_recurring_income(
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return FamilyRecurringIncomeCreateResponse(
            message="Recurring income created successfully",
            income_id=income.id,
            document_id=income.document_id,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error creating recurring income: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create recurring income",
        )


@router.patch(
    "/{income_id}",
    response_model=FamilyRecurringIncomeUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update recurring income (owner only)",
)
async def update_recurring_income(
    income_owner: LoggedInRecurringIncomeOwnerDep,
    income_service: IncomeServiceDep,
    data: Annotated[RecurringIncomeUpdateRequest, Depends(RecurringIncomeUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    income_id: UUID = Path(...),
) -> FamilyRecurringIncomeUpdateResponse:
    _owner, income = income_owner
    try:
        updated = await income_service.update_recurring_income(
            income=income,
            data=data,
            document=document,
        )
        return FamilyRecurringIncomeUpdateResponse(
            message="Recurring income updated successfully",
            income_id=updated.id,
            document_id=updated.document_id,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error updating recurring income: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update recurring income",
        )


@router.post(
    "/{income_id}/cancel",
    response_model=FamilyRecurringIncomeUpdateResponse,
    summary="Cancel recurring income",
)
async def cancel_recurring_income(
    income_owner: LoggedInRecurringIncomeOwnerDep,
    income_service: IncomeServiceDep,
    income_id: UUID = Path(...),
) -> FamilyRecurringIncomeUpdateResponse:
    _owner, income = income_owner
    try:
        updated = await income_service.cancel_recurring_income(income)
        return FamilyRecurringIncomeUpdateResponse(
            message="Recurring income cancelled",
            income_id=updated.id,
            document_id=updated.document_id,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
