from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.category.category_model import FosCategory
from app.api.routes.category.category_schemas import (
    CategoryCreateRequest,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdateRequest,
)
from app.api.routes.category.category_service import CategoryService
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/categories", tags=["categories"])


def get_category_service(session: PGSessionDep) -> CategoryService:
    return CategoryService(session)


def _resp(cat: FosCategory, can_edit: bool) -> CategoryResponse:
    data = CategoryResponse.model_validate(cat, from_attributes=True)
    data.can_edit = can_edit
    return data


@router.get("", response_model=CategoryListResponse, status_code=status.HTTP_200_OK)
async def list_categories(
    current_user: CurrentUserDep,
    pagination: PaginationDep,
    service: CategoryService = Depends(get_category_service),
    scope: str = Query(default="FAMILY"),
    category_type: str = Query(default="EXPENSE"),
    family_id: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=64),
) -> CategoryListResponse:
    items, total, is_head = await service.list_categories(
        user_id=current_user.id,
        scope=scope,
        category_type=category_type,
        family_id=family_id,
        pagination=pagination,
        q=q,
    )
    return CategoryListResponse.from_page(
        [
            _resp(c, c.scope == "PERSONAL" or is_head or c.owner_user_id == current_user.id)
            for c in items
        ],
        total=total,
        pagination=pagination,
    )


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    req: CategoryCreateRequest,
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
) -> CategoryResponse:
    cat = await service.create_category(user_id=current_user.id, req=req)
    return _resp(cat, await service.can_edit(current_user.id, cat))


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    req: CategoryUpdateRequest,
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
) -> CategoryResponse:
    cat = await service.update_category(current_user.id, category_id, req)
    return _resp(cat, True)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    current_user: CurrentUserDep,
    service: CategoryService = Depends(get_category_service),
) -> None:
    await service.delete_category(user_id=current_user.id, category_id=category_id)
