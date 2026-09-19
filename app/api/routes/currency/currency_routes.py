import logging
from decimal import Decimal
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.dependencies import AuthenticatedDep as CurrentUserDep
from app.api.db_dependencies import PGSessionDep as SessionDep
from app.api.routes.currency.model import CurrencyRate
from app.api.routes.currency.currency_schemas import (
    CurrencyRateCreate,
    CurrencyRateUpdate,
    CurrencyRateResponse,
    CurrencyRateListResponse,
)
from app.core.currency_service import convert as convert_amount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/currency-rates", tags=["currency"])


@router.get("/convert", response_model=dict)
async def convert_currency(
    user: CurrentUserDep,
    session: SessionDep,
    amount: Decimal,
    base: str,
    quote: str,
):
    result = await convert_amount(session, amount, base.upper(), quote.upper())
    return result.to_dict()


@router.get("", response_model=CurrencyRateListResponse)
async def list_currency_rates(
    user: CurrentUserDep,
    session: SessionDep,
):
    stmt = select(CurrencyRate).order_by(CurrencyRate.base_currency, CurrencyRate.quote_currency, CurrencyRate.effective_from.desc())
    result = await session.execute(stmt)
    rates = result.scalars().all()
    
    # Manually format them correctly
    items = []
    for r in rates:
        items.append(CurrencyRateResponse(
            id=r.id,
            baseCurrency=r.base_currency,
            quoteCurrency=r.quote_currency,
            rate=r.rate,
            status=r.status,
            effectiveFrom=r.effective_from,
            finalizedBy=r.finalized_by,
            finalizedAt=r.finalized_at,
            createdAt=r.created_at,
        ))
    
    return CurrencyRateListResponse(items=items)


@router.post("", response_model=CurrencyRateResponse)
async def create_currency_rate(
    user: CurrentUserDep,
    session: SessionDep,
    req: CurrencyRateCreate,
):
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only super admins can create currency rates")

    rate = CurrencyRate(
        base_currency=req.baseCurrency,
        quote_currency=req.quoteCurrency,
        rate=req.rate,
        effective_from=req.effectiveFrom,
        status="DRAFT",
    )
    session.add(rate)
    await session.commit()
    
    return CurrencyRateResponse(
        id=rate.id,
        baseCurrency=rate.base_currency,
        quoteCurrency=rate.quote_currency,
        rate=rate.rate,
        status=rate.status,
        effectiveFrom=rate.effective_from,
        finalizedBy=rate.finalized_by,
        finalizedAt=rate.finalized_at,
        createdAt=rate.created_at,
    )


@router.post("/{rate_id}/finalize", response_model=CurrencyRateResponse)
async def finalize_currency_rate(
    user: CurrentUserDep,
    session: SessionDep,
    rate_id: UUID,
):
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only super admins can finalize currency rates")

    rate = await session.get(CurrencyRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="Rate not found")
        
    rate.status = "FINAL"
    rate.finalized_by = user.id
    rate.finalized_at = datetime.now(timezone.utc)
    
    await session.commit()
    
    return CurrencyRateResponse(
        id=rate.id,
        baseCurrency=rate.base_currency,
        quoteCurrency=rate.quote_currency,
        rate=rate.rate,
        status=rate.status,
        effectiveFrom=rate.effective_from,
        finalizedBy=rate.finalized_by,
        finalizedAt=rate.finalized_at,
        createdAt=rate.created_at,
    )
