"""User-scoped personal transfers (PERSONAL→PERSONAL / PERSONAL→FAMILY)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import TransferServiceDep
from app.api.routes.transfer.transfer_schemas import (
    TransferCreateRequest,
    TransferListResponse,
    TransferResponse,
)
from app.config import feature_settings
from app.core.funding_service import InsufficientFundsError

router = APIRouter(prefix="/transfers", tags=["personal-transfers"])


def _require_transfers() -> None:
    if not feature_settings.FEATURE_TRANSFERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _resp(transfer, direction: str | None = None) -> TransferResponse:
    data = transfer.model_dump()
    data["direction"] = direction
    return TransferResponse.model_validate(data)


@router.get("", response_model=TransferListResponse)
async def list_personal_transfers(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
) -> TransferListResponse:
    _require_transfers()
    items = await transfer_service.list_personal_transfers(user.id)
    return TransferListResponse(items=[_resp(t, d) for t, d in items])


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    request: TransferCreateRequest,
) -> TransferResponse:
    _require_transfers()
    try:
        transfer = await transfer_service.create_personal_transfer(user.id, request)
        return _resp(transfer, "SENT")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientFundsError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_personal_transfer(transfer_id, user.id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.cancel_transfer(
            transfer, user.id, is_manager=False
        )
        return _resp(updated, "SENT")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await transfer_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/accept", response_model=TransferResponse)
async def accept_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_personal_transfer(transfer_id, user.id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.accept_transfer(transfer, user.id)
        return _resp(updated, "RECEIVED")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{transfer_id}/decline", response_model=TransferResponse)
async def decline_personal_transfer(
    user: LoggedInUserDep,
    transfer_service: TransferServiceDep,
    transfer_id: UUID,
) -> TransferResponse:
    _require_transfers()
    transfer = await transfer_service.get_personal_transfer(transfer_id, user.id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    try:
        updated = await transfer_service.decline_transfer(transfer, user.id)
        return _resp(updated, "RECEIVED")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
