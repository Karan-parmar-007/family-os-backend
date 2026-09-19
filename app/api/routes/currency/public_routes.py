from fastapi import APIRouter
from sqlalchemy import select
from app.api.db_dependencies import PGSessionDep
from app.api.routes.currency.model import FosCurrency
from app.api.routes.currency.currency_schemas import (
    FosCurrencyListResponse,
    FosCurrencyResponse,
)

router = APIRouter(prefix="/currencies", tags=["currencies"])


@router.get("", response_model=FosCurrencyListResponse, summary="List active currencies catalog")
async def list_active_currencies(session: PGSessionDep) -> FosCurrencyListResponse:
    stmt = select(FosCurrency).where(FosCurrency.is_active == True).order_by(FosCurrency.code)
    result = await session.execute(stmt)
    currencies = result.scalars().all()
    return FosCurrencyListResponse(
        items=[FosCurrencyResponse.model_validate(c) for c in currencies]
    )
