from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.category.category_schemas import (
    CategoryCreateRequest,
    CategoryListResponse,
    CategoryResponse,
)
from app.api.routes.category.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])


def get_category_service(session: PGSessionDep) -> CategoryService:
    return CategoryService(session)


@router.get("", response_model=CategoryListResponse, status_code=status.HTTP_200_OK)
async def list_categories(
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
    scope: str = Query(default="FAMILY"),
    category_type: str = Query(default="EXPENSE"),
    family_id: Optional[UUID] = Query(default=None),
) -> CategoryListResponse:
    """Fetch categories for the given scope and type (INCOME, EXPENSE, DEBT, ASSET, VAULT_PASSWORD, VAULT_DOCUMENT)."""
    items = await service.list_categories(
        user_id=current_user.id,
        scope=scope.upper(),
        category_type=category_type.upper(),
        family_id=family_id,
    )
    return CategoryListResponse(
        items=[CategoryResponse.model_validate(c, from_attributes=True) for c in items],
        total=len(items),
    )


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    req: CategoryCreateRequest,
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
) -> CategoryResponse:
    """Create a new custom category."""
    cat = await service.create_category(user_id=current_user.id, req=req)
    return CategoryResponse.model_validate(cat, from_attributes=True)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
) -> None:
    """Delete a custom category."""
    await service.delete_category(user_id=current_user.id, category_id=category_id)
