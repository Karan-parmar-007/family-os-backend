"""Personal transfers: from your personal savings, and offers sent to you."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import TransferServiceDep
from app.api.routes.transfer.transfer_http import build_responses, http_errors, one, require_transfers
from app.api.routes.transfer.transfer_schemas import (
    CodeLookupResponse,
    TransferCreateRequest,
    TransferListResponse,
    TransferResponse,
    TransferUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/transfers", tags=["personal-transfers"])


async def _get(transfer_service, transfer_id: UUID, user_id: UUID):
    transfer = await transfer_service.get_personal_transfer(transfer_id, user_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    return transfer


@router.get("", response_model=TransferListResponse)
async def list_personal_transfers(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    pagination: PaginationDep,
    status_filter: str | None = Query(default=None, alias="status"),
) -> TransferListResponse:
    require_transfers()
    rows, total = await transfer_service.list_personal_transfers(user.id, pagination, status=status_filter)
    items = await build_responses(transfer_service, rows, user.id)
    return TransferListResponse.from_page(items, total=total, pagination=pagination)


@router.get("/lookup", response_model=CodeLookupResponse)
async def lookup_code(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    code: str = Query(..., min_length=4, max_length=32),
) -> CodeLookupResponse:
    require_transfers()
    async with http_errors(transfer_service):
        found = await transfer_service.lookup_code(user.id, code, from_scope="PERSONAL", family_id=None)
    return CodeLookupResponse.model_validate(found)


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    request: TransferCreateRequest,
) -> TransferResponse:
    require_transfers()
    async with http_errors(transfer_service):
        transfer = await transfer_service.create_personal_transfer(user.id, request)
    return await one(transfer_service, transfer, "SENT", user.id)


@router.patch("/{transfer_id}", response_model=TransferResponse)
async def update_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    request: TransferUpdateRequest,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, user.id)
    async with http_errors(transfer_service):
        updated = await transfer_service.update_transfer(transfer, user.id, request)
    return await one(transfer_service, updated, "SENT", user.id)


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, user.id)
    async with http_errors(transfer_service):
        updated = await transfer_service.cancel_transfer(transfer, user.id)
    return await one(transfer_service, updated, "SENT", user.id)


@router.post("/{transfer_id}/accept", response_model=TransferResponse)
async def accept_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, user.id)
    async with http_errors(transfer_service):
        updated = await transfer_service.accept_transfer(transfer, user.id)
    return await one(transfer_service, updated, "RECEIVED", user.id)


@router.post("/{transfer_id}/decline", response_model=TransferResponse)
async def decline_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, user.id)
    async with http_errors(transfer_service):
        updated = await transfer_service.decline_transfer(transfer, user.id)
    return await one(transfer_service, updated, "RECEIVED", user.id)
