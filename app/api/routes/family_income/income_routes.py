import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import IncomeServiceDep
from app.api.routes.family_income.income_schemas import (
    FamilyIncomeLogCreateRequest,
    FamilyIncomeLogCreateResponse,
    FamilyIncomeLogDetailResponse,
    FamilyIncomeLogListResponse,
    FamilyIncomeLogListItem,
    FamilyIncomeLogUpdateRequest,
    FamilyIncomeLogUpdateResponse,
    RecurringIncomeQuickAddRequest,
    RecurringIncomeUpdateRequest,
    FamilyRecurringIncomeSummary,
    FamilyRecurringIncomeSummaryListResponse,
    FamilyRecurringIncomeCreateResponse,
    FamilyRecurringIncomeUpdateResponse,
    FamilyRecurringIncomeMineListResponse,
    IncomeCategoryCreateRequest,
    IncomeCategoryResponse,
    IncomeCategoryListResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.core.scope import load_scope_context, require_income_log_visible
from app.core.split_log_helpers import fetch_log_funding_sources

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/families/{family_id}/incomes",
    tags=["family-income"],
)


@router.get("/categories", response_model=IncomeCategoryListResponse)
async def list_categories(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    family_id: UUID = Path(..., description="ID of the family"),
) -> IncomeCategoryListResponse:
    items = await income_service.list_categories(family_id)
    return IncomeCategoryListResponse(
        items=[IncomeCategoryResponse.model_validate(i) for i in items]
    )


@router.post(
    "/categories",
    response_model=IncomeCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    request: IncomeCategoryCreateRequest,
    family_id: UUID = Path(..., description="ID of the family"),
) -> IncomeCategoryResponse:
    cat = await income_service.create_category(family_id, request)
    return IncomeCategoryResponse.model_validate(cat)


# ---------------------------------------------------------------------------
# Logs — paginated list (all members, limited fields)
# ---------------------------------------------------------------------------

@router.get(
    "/logs",
    response_model=FamilyIncomeLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List family income logs (paginated)",
    description=(
        "Fetch a paginated list of family income logs with optional filters. "
        "Returns limited fields: income_name, display amount, source_type, earned_by_user_name, income_date. "
        "The `can_edit` field indicates whether the current user may edit that log."
    ),
)
async def list_family_income_logs(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
    start_date: datetime | None = Query(default=None, description="Filter logs on or after this date (ISO 8601)"),
    end_date: datetime | None = Query(default=None, description="Filter logs on or before this date (ISO 8601)"),
    earned_by_user_id: UUID | None = Query(default=None, description="Filter by the user who earned this income"),
    category_id: UUID | None = Query(default=None, description="Filter by income category"),
) -> FamilyIncomeLogListResponse:
    """List family income logs with optional date/user/category filters."""
    scope_ctx = await load_scope_context(
        income_service.pg_session, family_member.id, family_id
    )
    items, total_count = await income_service.list_family_income_logs(
        family_id=family_id,
        current_user_id=family_member.id,
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
        earned_by_user_id=earned_by_user_id,
        category_id=category_id,
        scope_ctx=scope_ctx,
    )

    return FamilyIncomeLogListResponse.from_page(
        items,
        total=total_count,
        pagination=pagination,
    )


# ---------------------------------------------------------------------------
# Logs — full detail (for edit modal)
# ---------------------------------------------------------------------------

@router.get(
    "/logs/{log_id}",
    response_model=FamilyIncomeLogDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full detail of a family income log",
    description=(
        "Fetch all fields of a single income log. "
        "All family members can view; only the creator (added_by_user_id) may edit it."
    ),
)
async def get_family_income_log_detail(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    family_id: UUID = Path(..., description="ID of the family"),
    log_id: UUID = Path(..., description="ID of the income log"),
) -> FamilyIncomeLogDetailResponse:
    """Fetch full detail of a single income log including granular doc access list."""
    result = await income_service.get_family_income_log_detail_with_access(log_id=log_id, family_id=family_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Income log not found")
    log, viewer_ids = result
    try:
        await require_income_log_visible(
            income_service.pg_session, family_member.id, family_id, log
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    detail = FamilyIncomeLogDetailResponse.model_validate(log)
    detail.doc_viewer_user_ids = viewer_ids
    detail.funding_sources = await fetch_log_funding_sources(
        income_service.pg_session, "FAMILY_INCOME_LOG", log.id
    )
    return detail


# ---------------------------------------------------------------------------
# Logs — create
# ---------------------------------------------------------------------------

@router.post(
    "/logs",
    response_model=FamilyIncomeLogCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new family income log",
    description=(
        "Create a manual family income log. Automatically updates family total savings "
        "with the family_amount and personal total savings with the personal_savings_amount "
        "if applicable."
    ),
)
async def create_family_income_log(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    data: Annotated[FamilyIncomeLogCreateRequest, Depends(FamilyIncomeLogCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyIncomeLogCreateResponse:
    """Create a new family income log with automatic savings updates."""
    try:
        log, family_savings_updated, personal_savings_updated, personal_savings_user_id = (
            await income_service.create_family_income_log(
                family_id=family_id,
                logged_by_user_id=family_member.id,
                data=data,
                document=document,
            )
        )

        return FamilyIncomeLogCreateResponse(
            message="Family income log created successfully",
            log_id=log.id,
            family_savings_updated=family_savings_updated,
            personal_savings_updated=personal_savings_updated,
            personal_savings_user_id=personal_savings_user_id,
        )
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error creating family income log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create family income log",
        )


# ---------------------------------------------------------------------------
# Logs — update (owner only)
# ---------------------------------------------------------------------------

@router.patch(
    "/logs/{log_id}",
    response_model=FamilyIncomeLogUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a family income log",
    description=(
        "Partially update a family income log. Only the user who originally added it may edit. "
        "Savings totals are automatically adjusted: family_amount changes adjust family total savings; "
        "earned_by_user_id changes transfer personal savings between users. "
        "total_amount must always equal family_amount + personal_savings_amount."
    ),
)
async def update_family_income_log(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    data: Annotated[FamilyIncomeLogUpdateRequest, Depends(FamilyIncomeLogUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
    log_id: UUID = Path(..., description="ID of the income log to update"),
) -> FamilyIncomeLogUpdateResponse:
    """Partially update a family income log with automatic savings adjustments."""
    try:
        log, family_savings_delta, personal_savings_delta, personal_savings_user_id = (
            await income_service.update_family_income_log(
                log_id=log_id,
                family_id=family_id,
                logged_by_user_id=family_member.id,
                data=data,
                document=document,
            )
        )

        return FamilyIncomeLogUpdateResponse(
            message="Family income log updated successfully",
            log_id=log.id,
            family_savings_updated=family_savings_delta,
            personal_savings_updated=personal_savings_delta,
            personal_savings_user_id=personal_savings_user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await income_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await income_service.pg_session.rollback()
        logger.error("Error updating family income log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update family income log",
        )


# ---------------------------------------------------------------------------
# Recurring incomes — list all (summary, every member)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=FamilyRecurringIncomeSummaryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all family recurring incomes (summary)",
    description=(
        "Fetch a paginated summary of every recurring income in the family. "
        "Visible to all family members. Returns income_name, amount_to_be_added_to_family, "
        "received_every, and next_receiving_date only."
    ),
)
async def list_family_recurring_incomes(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringIncomeSummaryListResponse:
    """List recurring income splits visible in this family (read-only)."""
    items, total_count = await income_service.list_family_recurring_income_splits(
        family_id=family_id,
        pagination=pagination,
    )

    return FamilyRecurringIncomeSummaryListResponse.from_page(
        items,
        total=total_count,
        pagination=pagination,
    )


@router.post(
    "/recurring-quick-add",
    response_model=FamilyRecurringIncomeCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Quick-add recurring income for this family + personal",
)
async def quick_add_family_recurring_income(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    data: Annotated[RecurringIncomeQuickAddRequest, Depends(RecurringIncomeQuickAddRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringIncomeCreateResponse:
    try:
        income = await income_service.quick_add_recurring_income(
            user_id=family_member.id,
            family_id=family_id,
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
        logger.error("Error quick-adding recurring income: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create recurring income",
        )


@router.get(
    "/recurring/mine",
    response_model=FamilyRecurringIncomeMineListResponse,
    status_code=status.HTTP_200_OK,
    summary="List family-managed recurring incomes the current user may edit in this family",
)
async def list_my_family_managed_recurring_incomes(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringIncomeMineListResponse:
    items, total_count = await income_service.list_my_family_managed_recurring_incomes(
        user_id=family_member.id,
        family_id=family_id,
        pagination=pagination,
    )
    return FamilyRecurringIncomeMineListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.patch(
    "/recurring/{income_id}",
    response_model=FamilyRecurringIncomeUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a family-managed recurring income",
)
async def update_family_managed_recurring_income(
    family_member: LoggedInFamilyMemberDep,
    income_service: IncomeServiceDep,
    data: Annotated[RecurringIncomeUpdateRequest, Depends(RecurringIncomeUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
    income_id: UUID = Path(..., description="ID of the recurring income"),
) -> FamilyRecurringIncomeUpdateResponse:
    from sqlalchemy import select

    from app.api.routes.family_income.model import RecurringIncome

    stmt = select(RecurringIncome).where(RecurringIncome.id == income_id)
    income = (await income_service.pg_session.execute(stmt)).scalar_one_or_none()
    if income is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring income not found")
    if not income.is_family_managed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use personal income settings for this recurring income",
        )
    if not await income_service.can_edit_recurring_income(
        family_member.id, income, family_id=family_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot edit this recurring income",
        )
    try:
        updated = await income_service.update_recurring_income(
            income=income,
            data=data,
            document=document,
            document_family_id=family_id,
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
        logger.error("Error updating family recurring income: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update recurring income",
        )
