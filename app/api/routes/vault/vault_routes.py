import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, status

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.vault.model import FosVaultItem
from app.api.routes.vault.vault_schemas import (
    VaultPinSetupRequest,
    VaultUnlockRequest,
    VaultUnlockResponse,
    VaultItemCreateRequest,
    VaultItemResponse,
    VaultItemListResponse,
    VaultItemUpdateRequest,
)
from app.api.routes.vault.vault_service import VaultService, _decrypt_secret
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["vault"])


def get_vault_service(session: PGSessionDep) -> VaultService:
    return VaultService(session)


def _format(item: FosVaultItem, *, can_edit: bool, reveal: bool) -> VaultItemResponse:
    secret = None
    if item.ciphertext and (reveal or not item.is_protected):
        try:
            secret = _decrypt_secret(item.ciphertext)
        except Exception:
            logger.warning("Vault item %s could not be decrypted", item.id)
            secret = "[Decryption Error]"
    return VaultItemResponse(
        id=item.id,
        scope=item.scope,
        family_id=item.family_id,
        owner_user_id=item.owner_user_id,
        kind=item.kind,
        title=item.title,
        category=item.category,
        category_id=item.category_id,
        for_party_type=item.for_party_type,
        for_user_id=item.for_user_id,
        document_id=item.document_id,
        is_protected=item.is_protected,
        let_everyone_edit=item.let_everyone_edit,
        can_edit=can_edit,
        secret=secret,
        file_key=item.file_key,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post("/setup-pin", status_code=status.HTTP_200_OK)
async def setup_vault_pin(
    request: VaultPinSetupRequest,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
):
    await service.setup_pin(current_user.id, request.scope, request.family_id, request.pin)
    return {"message": "Vault PIN configured successfully"}


@router.post("/unlock", response_model=VaultUnlockResponse)
async def unlock_vault(
    request: VaultUnlockRequest,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
) -> VaultUnlockResponse:
    token = await service.unlock(current_user.id, request.scope, request.family_id, request.pin)
    return VaultUnlockResponse(token=token, expires_in_seconds=1200)


@router.get("/items", response_model=VaultItemListResponse)
async def list_vault_items(
    current_user: CurrentUserDep,
    pagination: PaginationDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    kind: Optional[str] = Query(default=None, description="PASSWORD | FILE"),
    category_id: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=100),
    x_vault_token: Optional[str] = Header(default=None, alias="X-Vault-Token"),
    service: VaultService = Depends(get_vault_service),
) -> VaultItemListResponse:
    is_unlocked = service.verify_unlock_token(x_vault_token, scope, family_id)
    items, total, pin_configured, is_head, password_count, document_count = await service.list_items(
        current_user.id,
        scope,
        family_id,
        pagination=pagination,
        kind=kind,
        category_id=category_id,
        q=q,
    )
    formatted = [
        _format(
            item,
            can_edit=await service.can_edit(current_user.id, item, is_head=is_head),
            reveal=is_unlocked,
        )
        for item in items
    ]
    return VaultItemListResponse.from_page(
        formatted,
        total=total,
        pagination=pagination,
        pin_configured=pin_configured,
        is_unlocked=is_unlocked,
        password_count=password_count,
        document_count=document_count,
    )


@router.post("/items", response_model=VaultItemResponse, status_code=status.HTTP_201_CREATED)
async def create_vault_item(
    request: VaultItemCreateRequest,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
) -> VaultItemResponse:
    item = await service.create_item(current_user.id, request)
    return _format(item, can_edit=True, reveal=True)


@router.patch("/items/{item_id}", response_model=VaultItemResponse)
async def update_vault_item(
    item_id: UUID,
    request: VaultItemUpdateRequest,
    current_user: CurrentUserDep,
    x_vault_token: Optional[str] = Header(default=None, alias="X-Vault-Token"),
    service: VaultService = Depends(get_vault_service),
) -> VaultItemResponse:
    item = await service.update_item(current_user.id, item_id, request)
    reveal = service.verify_unlock_token(x_vault_token, item.scope, item.family_id)
    return _format(item, can_edit=True, reveal=reveal)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vault_item(
    item_id: UUID,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
):
    await service.delete_item(current_user.id, item_id)
