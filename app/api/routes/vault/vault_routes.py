import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.vault.vault_schemas import (
    VaultPinSetupRequest,
    VaultUnlockRequest,
    VaultUnlockResponse,
    VaultItemCreateRequest,
    VaultItemResponse,
    VaultItemListResponse,
)
from app.api.routes.vault.vault_service import VaultService, _decrypt_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["vault"])


def get_vault_service(session: PGSessionDep) -> VaultService:
    return VaultService(session)


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
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    x_vault_token: Optional[str] = Header(default=None, alias="X-Vault-Token"),
    service: VaultService = Depends(get_vault_service),
) -> VaultItemListResponse:
    is_unlocked = service.verify_unlock_token(x_vault_token, scope, family_id)
    items, pin_configured = await service.list_items(current_user.id, scope, family_id, is_unlocked)

    formatted = []
    for item in items:
        # Decrypt secret only if unlocked or unprotected
        secret = None
        if item.ciphertext:
            if not item.is_protected or is_unlocked:
                try:
                    secret = _decrypt_secret(item.ciphertext)
                except Exception:
                    secret = "[Decryption Error]"

        formatted.append(
            VaultItemResponse(
                id=item.id,
                scope=item.scope,
                family_id=item.family_id,
                owner_user_id=item.owner_user_id,
                kind=item.kind,
                title=item.title,
                category=item.category,
                for_party_type=item.for_party_type,
                for_user_id=item.for_user_id,
                is_protected=item.is_protected,
                secret=secret,
                file_key=item.file_key,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    return VaultItemListResponse(
        items=formatted,
        pin_configured=pin_configured,
        is_unlocked=is_unlocked,
    )


@router.post("/items", response_model=VaultItemResponse, status_code=status.HTTP_201_CREATED)
async def create_vault_item(
    request: VaultItemCreateRequest,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
) -> VaultItemResponse:
    item = await service.create_item(current_user.id, request)
    return VaultItemResponse(
        id=item.id,
        scope=item.scope,
        family_id=item.family_id,
        owner_user_id=item.owner_user_id,
        kind=item.kind,
        title=item.title,
        category=item.category,
        for_party_type=item.for_party_type,
        for_user_id=item.for_user_id,
        is_protected=item.is_protected,
        secret=request.secret,
        file_key=item.file_key,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vault_item(
    item_id: UUID,
    current_user: CurrentUserDep,
    service: VaultService = Depends(get_vault_service),
):
    await service.delete_item(current_user.id, item_id)
