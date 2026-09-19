"""User-scoped personal income log routes."""

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import IncomeServiceDep
from app.api.routes.family_income.income_schemas import (
    PersonalIncomeLogCreateRequest,
    PersonalIncomeLogCreateResponse,
    PersonalIncomeLogDetailResponse,
    PersonalIncomeLogListResponse,
    PersonalIncomeLogUpdateRequest,
    PersonalIncomeLogUpdateResponse,
)
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incomes/logs", tags=["personal-income-logs"])


@router.get(
    "",
    response_model=PersonalIncomeLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List personal income received by the current user",
)
async def list_my_income_logs(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    pagination: PaginationDep,
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    category_id: UUID | None = Query(default=None, description="Filter by income category"),
) -> PersonalIncomeLogListResponse:
    items, total_count = await income_service.list_personal_income_logs(
        user_id=current_user.id,
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
    )
    return PersonalIncomeLogListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.get(
    "/{log_id}",
    response_model=PersonalIncomeLogDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get detail of a personal income log",
)
async def get_my_income_log_detail(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    log_id: UUID = Path(...),
) -> PersonalIncomeLogDetailResponse:
    log = await income_service.get_personal_income_log_detail(
        log_id=log_id, user_id=current_user.id
    )
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income log not found")
    detail = PersonalIncomeLogDetailResponse.model_validate(log)
    detail.can_edit = log.source_type == "MANUAL" and log.logged_by == current_user.id
    return detail


@router.post(
    "",
    response_model=PersonalIncomeLogCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual personal income log",
)
async def create_my_income_log(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    data: Annotated[PersonalIncomeLogCreateRequest, Depends(PersonalIncomeLogCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
) -> PersonalIncomeLogCreateResponse:
    try:
        log, personal_updated = await income_service.create_personal_income_log(
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return PersonalIncomeLogCreateResponse(
            message="Personal income log created successfully",
            log_id=log.id,
            personal_savings_updated=personal_updated,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error creating personal income log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create income log",
        )


@router.patch(
    "/{log_id}",
    response_model=PersonalIncomeLogUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a manual personal income log",
)
async def update_my_income_log(
    current_user: LoggedInUserDep,
    income_service: IncomeServiceDep,
    data: Annotated[PersonalIncomeLogUpdateRequest, Depends(PersonalIncomeLogUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    log_id: UUID = Path(...),
) -> PersonalIncomeLogUpdateResponse:
    try:
        updated, personal_delta = await income_service.update_personal_income_log(
            log_id=log_id,
            user_id=current_user.id,
            data=data,
            document=document,
        )
        return PersonalIncomeLogUpdateResponse(
            message="Personal income log updated successfully",
            log_id=updated.id,
            personal_savings_delta=personal_delta,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error updating personal income log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update income log",
        )
