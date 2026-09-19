"""User-scoped recurring expense routes (personal management)."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.expense_owner import LoggedInRecurringExpenseOwnerDep
from app.api.dependencies import RecurringExpenseServiceDep
from app.api.routes.family_expense.expense_schemas import (
    RecurringExpenseCreateRequest,
    RecurringExpenseMineListResponse,
    RecurringExpenseUpdateRequest,
    FamilyRecurringExpenseCreateResponse,
    FamilyRecurringExpenseUpdateResponse,
)
from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/expenses/recurring", tags=["recurring-expense"])


@router.get(
    "/mine",
    response_model=RecurringExpenseMineListResponse,
    status_code=status.HTTP_200_OK,
    summary="List current user's recurring expenses (full detail)",
)
async def list_my_recurring_expenses(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    pagination: PaginationDep,
    personal_only: bool = Query(
        default=True,
        description="When true (default), exclude family-page recurring expenses",
    ),
) -> RecurringExpenseMineListResponse:
    items, total_count = await expense_service.list_user_recurring_expenses(
        user_id=current_user.id,
        pagination=pagination,
        personal_only=personal_only,
    )
    return RecurringExpenseMineListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.post(
    "",
    response_model=FamilyRecurringExpenseCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create recurring expense with multi-family splits",
)
async def create_recurring_expense(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[RecurringExpenseCreateRequest, Depends(RecurringExpenseCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
) -> FamilyRecurringExpenseCreateResponse:
    try:
        expense = await expense_service.create_recurring_expense(
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return FamilyRecurringExpenseCreateResponse(
            message="Recurring expense created successfully",
            expense_id=expense.id,
            document_id=expense.document_id,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error creating recurring expense: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create recurring expense",
        )


@router.patch(
    "/{expense_id}",
    response_model=FamilyRecurringExpenseUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update recurring expense (owner only)",
)
async def update_recurring_expense(
    expense_owner: LoggedInRecurringExpenseOwnerDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[RecurringExpenseUpdateRequest, Depends(RecurringExpenseUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    expense_id: UUID = Path(...),
) -> FamilyRecurringExpenseUpdateResponse:
    _owner, expense = expense_owner
    try:
        updated = await expense_service.update_recurring_expense(
            expense=expense,
            data=data,
            document=document,
        )
        return FamilyRecurringExpenseUpdateResponse(
            message="Recurring expense updated successfully",
            expense_id=updated.id,
            document_id=updated.document_id,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error updating recurring expense: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update recurring expense",
        )


@router.post(
    "/{expense_id}/cancel",
    response_model=FamilyRecurringExpenseUpdateResponse,
    summary="Cancel recurring expense",
)
async def cancel_recurring_expense(
    expense_owner: LoggedInRecurringExpenseOwnerDep,
    expense_service: RecurringExpenseServiceDep,
    expense_id: UUID = Path(...),
) -> FamilyRecurringExpenseUpdateResponse:
    _owner, expense = expense_owner
    try:
        updated = await expense_service.cancel_recurring_expense(expense)
        return FamilyRecurringExpenseUpdateResponse(
            message="Recurring expense cancelled",
            expense_id=updated.id,
            document_id=updated.document_id,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
