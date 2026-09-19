import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import AssetsServiceDep
from app.api.routes.assets.assets_schemas import (
    AssetCreateRequest,
    AssetListResponse,
    AssetResponse,
    AssetUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/assets", tags=["assets"])


def _resp(asset, is_personal: bool) -> AssetResponse:
    data = asset.model_dump()
    data["is_personal"] = is_personal
    return AssetResponse.model_validate(data)


@router.get("", response_model=AssetListResponse)
async def list_assets(
    family_member: LoggedInFamilyMemberDep,
    assets_service: AssetsServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> AssetListResponse:
    scope_ctx = await load_scope_context(
        assets_service.pg_session, family_member.id, family_id
    )
    items, total, total_value = await assets_service.list_assets(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return AssetListResponse.from_page(
        [_resp(a, p) for a, p in items],
        total=total,
        pagination=pagination,
    ).model_copy(update={"total_value": total_value})


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    family_member: LoggedInFamilyMemberDep,
    assets_service: AssetsServiceDep,
    request: AssetCreateRequest,
    family_id: UUID,
) -> AssetResponse:
    asset, is_personal = await assets_service.create_asset(
        family_id, family_member.id, request
    )
    return _resp(asset, is_personal)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    family_member: LoggedInFamilyMemberDep,
    assets_service: AssetsServiceDep,
    family_id: UUID,
    asset_id: UUID,
) -> AssetResponse:
    found = await assets_service.get_asset(asset_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    asset, is_personal = found
    try:
        await require_entity_visible(
            assets_service.pg_session, family_member.id, family_id, asset, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _resp(asset, is_personal)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    family_member: LoggedInFamilyMemberDep,
    assets_service: AssetsServiceDep,
    request: AssetUpdateRequest,
    family_id: UUID,
    asset_id: UUID,
) -> AssetResponse:
    found = await assets_service.get_asset(asset_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    asset, is_personal = found
    try:
        await require_entity_editable(
            assets_service.pg_session, family_member.id, family_id, asset, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await assets_service.update_asset(asset, request)
    return _resp(updated, is_personal)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    family_member: LoggedInFamilyMemberDep,
    assets_service: AssetsServiceDep,
    family_id: UUID,
    asset_id: UUID,
) -> None:
    found = await assets_service.get_asset(asset_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    asset, is_personal = found
    try:
        await require_entity_editable(
            assets_service.pg_session, family_member.id, family_id, asset, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await assets_service.delete_asset(asset)
