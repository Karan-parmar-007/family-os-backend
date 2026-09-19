"""User-scoped personal expense log routes."""

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import RecurringExpenseServiceDep
from app.api.routes.family_expense.expense_schemas import (
    PersonalExpenseLogCreateRequest,
    PersonalExpenseLogCreateResponse,
    PersonalExpenseLogDetailResponse,
    PersonalExpenseLogListResponse,
    PersonalExpenseLogUpdateRequest,
    PersonalExpenseLogUpdateResponse,
)
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/expenses/logs", tags=["personal-expense-logs"])


@router.get(
    "",
    response_model=PersonalExpenseLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List personal expenses paid by the current user",
)
async def list_my_expense_logs(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    pagination: PaginationDep,
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    category_id: UUID | None = Query(default=None, description="Filter by expense category"),
) -> PersonalExpenseLogListResponse:
    items, total_count = await expense_service.list_personal_expense_logs(
        user_id=current_user.id,
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
    )
    return PersonalExpenseLogListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.get(
    "/{log_id}",
    response_model=PersonalExpenseLogDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get detail of a personal expense log",
)
async def get_my_expense_log_detail(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    log_id: UUID = Path(...),
) -> PersonalExpenseLogDetailResponse:
    log = await expense_service.get_personal_expense_log_detail(
        log_id=log_id, user_id=current_user.id
    )
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense log not found")
    detail = PersonalExpenseLogDetailResponse.model_validate(log)
    detail.can_edit = log.source_type == "MANUAL" and log.logged_by == current_user.id
    return detail


@router.post(
    "",
    response_model=PersonalExpenseLogCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual personal expense log",
)
async def create_my_expense_log(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[PersonalExpenseLogCreateRequest, Depends(PersonalExpenseLogCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
) -> PersonalExpenseLogCreateResponse:
    try:
        log, personal_updated = await expense_service.create_personal_expense_log(
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return PersonalExpenseLogCreateResponse(
            message="Personal expense log created successfully",
            log_id=log.id,
            personal_savings_updated=personal_updated,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error creating personal expense log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create expense log",
        )


@router.patch(
    "/{log_id}",
    response_model=PersonalExpenseLogUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a manual personal expense log",
)
async def update_my_expense_log(
    current_user: LoggedInUserDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[PersonalExpenseLogUpdateRequest, Depends(PersonalExpenseLogUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    log_id: UUID = Path(...),
) -> PersonalExpenseLogUpdateResponse:
    try:
        updated, personal_delta = await expense_service.update_personal_expense_log(
            log_id=log_id,
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return PersonalExpenseLogUpdateResponse(
            message="Personal expense log updated successfully",
            log_id=updated.id,
            personal_savings_delta=personal_delta,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error updating personal expense log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update expense log",
        )
