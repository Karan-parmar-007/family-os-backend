import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import TransferServiceDep
from app.api.routes.transfer.transfer_schemas import (
    TransferCreateRequest,
    TransferDetailResponse,
    TransferListResponse,
    TransferResponse,
    TransferUpdateRequest,
)
from app.config import feature_settings
from app.core.funding_service import InsufficientFundsError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families/{family_id}/transfers", tags=["transfers"])


def _require_transfers() -> None:
    if not feature_settings.FEATURE_TRANSFERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _resp(transfer, direction: str | None = None) -> TransferResponse:
    data = transfer.model_dump()
    data["direction"] = direction
    return TransferResponse.model_validate(data)


@router.get("", response_model=TransferListResponse)
async def list_transfers(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
) -> TransferListResponse:
    _require_transfers()
    items = await transfer_service.list_transfers(family_id)
    return TransferListResponse(items=[_resp(t, d) for t, d in items])


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    request: TransferCreateRequest,
    family_id: UUID,
) -> TransferResponse:
    _require_transfers()
    try:
        transfer = await transfer_service.create_transfer(
            family_id, family_member.id, request
        )
        return _resp(transfer, "SENT")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientFundsError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{transfer_id}", response_model=TransferDetailResponse)
async def get_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferDetailResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    direction = "SENT" if transfer.family_id == family_id else "RECEIVED"
    return TransferDetailResponse.model_validate(_resp(transfer, direction))


@router.patch("/{transfer_id}", response_model=TransferResponse)
async def update_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    request: TransferUpdateRequest,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None or transfer.family_id != family_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.update_transfer(transfer, request)
        return _resp(updated, "SENT")
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/accept", response_model=TransferResponse)
async def accept_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.accept_transfer(transfer, family_member.id)
        return _resp(updated, "RECEIVED")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/decline", response_model=TransferResponse)
async def decline_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.decline_transfer(transfer, family_member.id)
        return _resp(updated, "RECEIVED")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None or transfer.family_id != family_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.cancel_transfer(
            transfer, family_member.id, is_manager=False
        )
        return _resp(updated, "SENT")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/reverse", response_model=TransferResponse)
async def reverse_transfer(
    family_member: LoggedInFamilyMemberDep,
    transfer_service: TransferServiceDep,
    family_id: UUID,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_transfer(transfer_id, family_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        reversed_transfer = await transfer_service.reverse_transfer(
            transfer, family_member.id, is_manager=False
        )
        return _resp(reversed_transfer, "SENT")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
