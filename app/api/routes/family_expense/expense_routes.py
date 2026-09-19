import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import RecurringExpenseServiceDep
from app.core.split_log_helpers import fetch_log_funding_sources
from app.api.routes.family_expense.expense_schemas import (
    FamilyExpenseLogCreateRequest,
    FamilyExpenseLogCreateResponse,
    FamilyExpenseLogDetailResponse,
    FamilyExpenseLogListResponse,
    FamilyExpenseLogListItem,
    FamilyExpenseLogUpdateRequest,
    FamilyExpenseLogUpdateResponse,
    RecurringExpenseQuickAddRequest,
    RecurringExpenseUpdateRequest,
    FamilyRecurringExpenseSummary,
    FamilyRecurringExpenseSummaryListResponse,
    FamilyRecurringExpenseCreateResponse,
    FamilyRecurringExpenseUpdateResponse,
    FamilyRecurringExpenseMineListResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.core.scope import load_scope_context, require_expense_log_visible

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/families/{family_id}/expenses",
    tags=["family-expense"],
)


# ---------------------------------------------------------------------------
# Logs — paginated list (all members, limited fields)
# ---------------------------------------------------------------------------

@router.get(
    "/logs",
    response_model=FamilyExpenseLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List family expense logs (paginated)",
    description=(
        "Fetch a paginated list of family expense logs with optional filters. "
        "Returns limited fields: expense_name, display amount, source_type, paid_by_user_name, expense_date. "
        "The `can_edit` field indicates whether the current user may edit that log."
    ),
)
async def list_family_expense_logs(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
    start_date: datetime | None = Query(default=None, description="Filter logs on or after this date (ISO 8601)"),
    end_date: datetime | None = Query(default=None, description="Filter logs on or before this date (ISO 8601)"),
    logged_by_user_id: UUID | None = Query(default=None, description="Filter by the user who logged this expense"),
    category_id: UUID | None = Query(default=None, description="Filter by expense category"),
) -> FamilyExpenseLogListResponse:
    """List family expense logs with optional date/user/category filters."""
    scope_ctx = await load_scope_context(
        expense_service.pg_session, family_member.id, family_id
    )
    items, total_count = await expense_service.list_family_expense_logs(
        family_id=family_id,
        current_user_id=family_member.id,
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
        logged_by_user_id=logged_by_user_id,
        category_id=category_id,
        scope_ctx=scope_ctx,
    )

    return FamilyExpenseLogListResponse.from_page(
        items,
        total=total_count,
        pagination=pagination,
    )


# ---------------------------------------------------------------------------
# Logs — full detail (for edit modal)
# ---------------------------------------------------------------------------

@router.get(
    "/logs/{log_id}",
    response_model=FamilyExpenseLogDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full detail of a family expense log",
    description=(
        "Fetch all fields of a single expense log. "
        "All family members can view; only the creator (added_by_user_id) may edit it."
    ),
)
async def get_family_expense_log_detail(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    family_id: UUID = Path(..., description="ID of the family"),
    log_id: UUID = Path(..., description="ID of the expense log"),
) -> FamilyExpenseLogDetailResponse:
    """Fetch full detail of a single expense log including granular doc access list."""
    result = await expense_service.get_family_expense_log_detail_with_access(log_id=log_id, family_id=family_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense log not found")
    log, viewer_ids = result
    try:
        await require_expense_log_visible(
            expense_service.pg_session, family_member.id, family_id, log
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    detail = FamilyExpenseLogDetailResponse.model_validate(log)
    detail.doc_viewer_user_ids = viewer_ids
    detail.funding_sources = await fetch_log_funding_sources(
        expense_service.pg_session, "FAMILY_EXPENSE_LOG", log.id
    )
    return detail


# ---------------------------------------------------------------------------
# Logs — create
# ---------------------------------------------------------------------------

@router.post(
    "/logs",
    response_model=FamilyExpenseLogCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new family expense log",
    description=(
        "Create a manual family expense log. Automatically updates family total savings "
        "with the family_amount and personal total savings with the personal_savings_amount "
        "if applicable."
    ),
)
async def create_family_expense_log(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[FamilyExpenseLogCreateRequest, Depends(FamilyExpenseLogCreateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyExpenseLogCreateResponse:
    """Create a new family expense log with automatic savings updates."""
    try:
        log, family_savings_updated, personal_savings_updated, personal_savings_user_id = (
            await expense_service.create_family_expense_log(
                family_id=family_id,
                logged_by_user_id=family_member.id,
                data=data,
                document=document,
            )
        )

        return FamilyExpenseLogCreateResponse(
            message="Family expense log created successfully",
            log_id=log.id,
            family_savings_updated=family_savings_updated,
            personal_savings_updated=personal_savings_updated,
            personal_savings_user_id=personal_savings_user_id,
        )
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error creating family expense log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create family expense log",
        )


# ---------------------------------------------------------------------------
# Logs — update (owner only)
# ---------------------------------------------------------------------------

@router.patch(
    "/logs/{log_id}",
    response_model=FamilyExpenseLogUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a family expense log",
    description=(
        "Partially update a family expense log. Only the user who originally added it may edit. "
        "Savings totals are automatically adjusted: family_amount changes adjust family total savings; "
        "paid_by_user_id changes transfer personal savings between users. "
        "total_amount must always equal family_amount + personal_savings_amount."
    ),
)
async def update_family_expense_log(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[FamilyExpenseLogUpdateRequest, Depends(FamilyExpenseLogUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
    log_id: UUID = Path(..., description="ID of the expense log to update"),
) -> FamilyExpenseLogUpdateResponse:
    """Partially update a family expense log with automatic savings adjustments."""
    try:
        log, family_savings_delta, personal_savings_delta, personal_savings_user_id = (
            await expense_service.update_family_expense_log(
                log_id=log_id,
                family_id=family_id,
                logged_by_user_id=family_member.id,
                data=data,
                document=document,
            )
        )

        return FamilyExpenseLogUpdateResponse(
            message="Family expense log updated successfully",
            log_id=log.id,
            family_savings_updated=family_savings_delta,
            personal_savings_updated=personal_savings_delta,
            personal_savings_user_id=personal_savings_user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await expense_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as e:
        await expense_service.pg_session.rollback()
        logger.error("Error updating family expense log: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update family expense log",
        )


# ---------------------------------------------------------------------------
# Recurring expenses — list all (summary, every member)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=FamilyRecurringExpenseSummaryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all family recurring expenses (summary)",
    description=(
        "Fetch a paginated summary of every recurring expense in the family. "
        "Visible to all family members. Returns expense_name, amount_to_be_added_to_family, "
        "paid_every, and next_payment_date only."
    ),
)
async def list_family_recurring_expenses(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringExpenseSummaryListResponse:
    """List recurring expense splits visible in this family (read-only)."""
    items, total_count = await expense_service.list_family_recurring_expense_splits(
        family_id=family_id,
        pagination=pagination,
    )

    return FamilyRecurringExpenseSummaryListResponse.from_page(
        items,
        total=total_count,
        pagination=pagination,
    )


@router.post(
    "/recurring-quick-add",
    response_model=FamilyRecurringExpenseCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Quick-add recurring expense for this family + personal",
)
async def quick_add_family_recurring_expense(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[RecurringExpenseQuickAddRequest, Depends(RecurringExpenseQuickAddRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringExpenseCreateResponse:
    try:
        expense = await expense_service.quick_add_recurring_expense(
            user_id=family_member.id,
            family_id=family_id,
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
        logger.error("Error quick-adding recurring expense: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create recurring expense",
        )


@router.get(
    "/recurring/mine",
    response_model=FamilyRecurringExpenseMineListResponse,
    status_code=status.HTTP_200_OK,
    summary="List family-managed recurring expenses the current user may edit in this family",
)
async def list_my_family_managed_recurring_expenses(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    pagination: PaginationDep,
    family_id: UUID = Path(..., description="ID of the family"),
) -> FamilyRecurringExpenseMineListResponse:
    items, total_count = await expense_service.list_my_family_managed_recurring_expenses(
        user_id=family_member.id,
        family_id=family_id,
        pagination=pagination,
    )
    return FamilyRecurringExpenseMineListResponse.from_page(
        items, total=total_count, pagination=pagination
    )


@router.patch(
    "/recurring/{expense_id}",
    response_model=FamilyRecurringExpenseUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a family-managed recurring expense",
)
async def update_family_managed_recurring_expense(
    family_member: LoggedInFamilyMemberDep,
    expense_service: RecurringExpenseServiceDep,
    data: Annotated[RecurringExpenseUpdateRequest, Depends(RecurringExpenseUpdateRequest.as_form)],
    document: UploadFile | None = File(default=None),
    family_id: UUID = Path(..., description="ID of the family"),
    expense_id: UUID = Path(..., description="ID of the recurring expense"),
) -> FamilyRecurringExpenseUpdateResponse:
    from sqlalchemy import select

    from app.api.routes.family_expense.model import RecurringExpense

    stmt = select(RecurringExpense).where(RecurringExpense.id == expense_id)
    expense = (await expense_service.pg_session.execute(stmt)).scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring expense not found")
    if not expense.is_family_managed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use personal expense settings for this recurring expense",
        )
    if not await expense_service.can_edit_recurring_expense(
        family_member.id, expense, family_id=family_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot edit this recurring expense",
        )
    try:
        updated = await expense_service.update_recurring_expense(
            expense=expense,
            data=data,
            document=document,
            document_family_id=family_id,
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
        logger.error("Error updating family recurring expense: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update recurring expense",
        )
