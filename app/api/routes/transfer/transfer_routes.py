import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import TransferServiceDep
from app.api.routes.transfer.transfer_http import build_responses, http_errors, one, require_transfers
from app.api.routes.transfer.transfer_schemas import (
    CodeLookupResponse,
    TransferCreateRequest,
    TransferDetailResponse,
    TransferListResponse,
    TransferResponse,
    TransferUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/transfers", tags=["transfers"])


def _direction(transfer, family_id: UUID) -> str:
    return "SENT" if transfer.from_scope == "FAMILY" and transfer.family_id == family_id else "RECEIVED"


async def _get(transfer_service, transfer_id: UUID, family_id: UUID):
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    return transfer


@router.get("", response_model=TransferListResponse)
async def list_transfers(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
    status_filter: str | None = Query(default=None, alias="status"),
) -> TransferListResponse:
    require_transfers()
    rows, total = await transfer_service.list_transfers(family_id, pagination, status=status_filter)
    items = await build_responses(transfer_service, rows, family_member.id)
    return TransferListResponse.from_page(items, total=total, pagination=pagination)


@router.get("/lookup", response_model=CodeLookupResponse)
async def lookup_code(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    code: str = Query(..., min_length=4, max_length=32),
) -> CodeLookupResponse:
    require_transfers()
    async with http_errors(transfer_service):
        found = await transfer_service.lookup_code(
            family_member.id, code, from_scope="FAMILY", family_id=family_id
        )
    return CodeLookupResponse.model_validate(found)


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    request: TransferCreateRequest,
    family_id: UUID,
) -> TransferResponse:
    require_transfers()
    request.from_scope = "FAMILY"
    async with http_errors(transfer_service):
        transfer = await transfer_service.create_transfer(family_id, family_member.id, request)
    return await one(transfer_service, transfer, "SENT", family_member.id)


@router.get("/{transfer_id}", response_model=TransferDetailResponse)
async def get_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferDetailResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, family_id)
    resp = await one(transfer_service, transfer, _direction(transfer, family_id), family_member.id)
    return TransferDetailResponse.model_validate(resp.model_dump())


@router.patch("/{transfer_id}", response_model=TransferResponse)
async def update_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    request: TransferUpdateRequest,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, family_id)
    async with http_errors(transfer_service):
        updated = await transfer_service.update_transfer(transfer, family_member.id, request)
    return await one(transfer_service, updated, "SENT", family_member.id)


@router.post("/{transfer_id}/accept", response_model=TransferResponse)
async def accept_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, family_id)
    async with http_errors(transfer_service):
        updated = await transfer_service.accept_transfer(transfer, family_member.id)
    return await one(transfer_service, updated, "RECEIVED", family_member.id)


@router.post("/{transfer_id}/decline", response_model=TransferResponse)
async def decline_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, family_id)
    async with http_errors(transfer_service):
        updated = await transfer_service.decline_transfer(transfer, family_member.id)
    return await one(transfer_service, updated, "RECEIVED", family_member.id)


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    require_transfers()
    transfer = await _get(transfer_service, transfer_id, family_id)
    async with http_errors(transfer_service):
        updated = await transfer_service.cancel_transfer(transfer, family_member.id)
    return await one(transfer_service, updated, "SENT", family_member.id)
