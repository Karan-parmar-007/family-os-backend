"""Personal assets routes — /api/personal/assets (Plan 03)."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import AssetsServiceDep
from app.api.routes.assets.assets_routes import _resp
from app.api.routes.assets.assets_schemas import (
    AssetCreateRequest,
    AssetListResponse,
    AssetResponse,
    AssetUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/personal/assets", tags=["personal-assets"])


@router.get("", response_model=AssetListResponse)
async def list_personal_assets(
    user: LoggedInUserDep,
    assets_service: AssetsServiceDep,
    pagination: PaginationDep,
) -> AssetListResponse:
    items, total, total_value = await assets_service.list_personal_assets(
        user.id, pagination
    )
    return AssetListResponse.from_page(
        [_resp(a, True) for a in items],
        total=total,
        pagination=pagination,
    ).model_copy(update={"total_value": total_value})


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_asset(
    user: LoggedInUserDep,
    assets_service: AssetsServiceDep,
    request: AssetCreateRequest,
    family_id: UUID,
) -> AssetResponse:
    asset = await assets_service.create_personal_asset(user.id, family_id, request)
    return _resp(asset, True)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_personal_asset(
    user: LoggedInUserDep,
    assets_service: AssetsServiceDep,
    asset_id: UUID,
) -> AssetResponse:
    asset = await assets_service.get_personal_asset(asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _resp(asset, True)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_personal_asset(
    user: LoggedInUserDep,
    assets_service: AssetsServiceDep,
    request: AssetUpdateRequest,
    asset_id: UUID,
) -> AssetResponse:
    asset = await assets_service.get_personal_asset(asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    updated = await assets_service.update_asset(asset, request)
    return _resp(updated, True)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_asset(
    user: LoggedInUserDep,
    assets_service: AssetsServiceDep,
    asset_id: UUID,
) -> None:
    asset = await assets_service.get_personal_asset(asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await assets_service.delete_asset(asset)
