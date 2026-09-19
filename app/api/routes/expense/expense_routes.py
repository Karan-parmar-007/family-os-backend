import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import ExpenseServiceDep
from app.api.routes.expense.expense_schemas import (
    ExpenseCategoryCreateRequest,
    ExpenseCategoryListResponse,
    ExpenseCategoryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/expenses", tags=["expense"])


@router.get("/categories", response_model=ExpenseCategoryListResponse)
async def list_categories(
    family_member: LoggedInFamilyMemberDep,
    expense_service: ExpenseServiceDep,
    family_id: UUID,
) -> ExpenseCategoryListResponse:
    items = await expense_service.list_categories(family_id)
    return ExpenseCategoryListResponse(
        items=[ExpenseCategoryResponse.model_validate(i) for i in items]
    )


@router.post(
    "/categories",
    response_model=ExpenseCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    family_member: LoggedInFamilyMemberDep,
    expense_service: ExpenseServiceDep,
    request: ExpenseCategoryCreateRequest,
    family_id: UUID,
) -> ExpenseCategoryResponse:
    cat = await expense_service.create_category(family_id, request)
    return ExpenseCategoryResponse.model_validate(cat)
