"""Response building and error mapping shared by the family and personal routers."""

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import HTTPException, status

from app.api.routes.transfer.model import Transfer
from app.api.routes.transfer.transfer_schemas import TransferResponse
from app.api.routes.transfer.transfer_service import CodeNotFoundError, TransferService
from app.config import feature_settings
from app.core.funding_service import InsufficientFundsError


def require_transfers() -> None:
    if not feature_settings.FEATURE_TRANSFERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfers are turned off")


async def build_responses(
    service: TransferService, rows: list[tuple[Transfer, str]], actor_id: UUID
) -> list[TransferResponse]:
    labels = await service.labels([t for t, _ in rows])
    out = []
    for t, direction in rows:
        data = t.model_dump()
        data.update(
            direction=direction,
            from_label=service.endpoint_label(labels, t.from_scope, t.family_id, t.from_user_id),
            to_label=service.endpoint_label(labels, t.to_scope, t.to_family_id, t.to_user_id),
            can_accept=await service.can_accept(t, actor_id),
            can_cancel=await service.can_cancel(t, actor_id),
        )
        out.append(TransferResponse.model_validate(data))
    return out


async def one(service: TransferService, transfer: Transfer, direction: str, actor_id: UUID) -> TransferResponse:
    return (await build_responses(service, [(transfer, direction)], actor_id))[0]


@asynccontextmanager
async def http_errors(service: TransferService):
    try:
        yield
    except HTTPException:
        raise
    except InsufficientFundsError as exc:
        await service.pg_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Not enough balance: {exc.available:,.2f} available, {exc.required:,.2f} needed",
        )
    except PermissionError as exc:
        await service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except CodeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        await service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
