from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.currency.model import CurrencyRate, FosCurrency

_CENTS = Decimal("0.01")


def _round2(d: Decimal) -> Decimal:
    return d.quantize(_CENTS, rounding=ROUND_HALF_UP)


async def get_rate(
    session: AsyncSession, base: str, quote: str
) -> Optional[Decimal]:
    """Return rate for base -> quote.

    1. Checks fos_currencies table (base.rate_to_usd / quote.rate_to_usd).
    2. Fallback to legacy currency_rates table if not found in fos_currencies.
    """
    base = base.upper().strip()
    quote = quote.upper().strip()

    if base == quote:
        return Decimal("1.0")

    # 1. FosCurrency check
    stmt_base = select(FosCurrency).where(FosCurrency.code == base)
    stmt_quote = select(FosCurrency).where(FosCurrency.code == quote)

    base_curr = (await session.execute(stmt_base)).scalar_one_or_none()
    quote_curr = (await session.execute(stmt_quote)).scalar_one_or_none()

    if base_curr is not None and quote_curr is not None:
        if quote_curr.rate_to_usd and quote_curr.rate_to_usd > 0:
            return base_curr.rate_to_usd / quote_curr.rate_to_usd

    # 2. Legacy fallback
    stmt = (
        select(CurrencyRate)
        .where(
            and_(
                CurrencyRate.base_currency == base,
                CurrencyRate.quote_currency == quote,
                CurrencyRate.status == "FINAL",
            )
        )
        .order_by(CurrencyRate.finalized_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row:
        return row.rate

    stmt_inv = (
        select(CurrencyRate)
        .where(
            and_(
                CurrencyRate.base_currency == quote,
                CurrencyRate.quote_currency == base,
                CurrencyRate.status == "FINAL",
            )
        )
        .order_by(CurrencyRate.finalized_at.desc())
        .limit(1)
    )
    row_inv = (await session.execute(stmt_inv)).scalar_one_or_none()
    if row_inv and row_inv.rate and row_inv.rate != 0:
        return Decimal("1") / row_inv.rate

    return None


class ConvertedAmount:
    def __init__(
        self,
        amount: Decimal,
        converted: Decimal,
        rate: Optional[Decimal],
        is_converted: bool,
        base_currency: str,
        quote_currency: str,
    ):
        self.amount = amount
        self.converted = converted
        self.rate = rate
        self.is_converted = is_converted
        self.base_currency = base_currency
        self.quote_currency = quote_currency

    def to_dict(self) -> dict:
        return {
            "amount": str(self.amount),
            "converted": str(self.converted),
            "rate": str(self.rate) if self.rate else None,
            "isConverted": self.is_converted,
            "baseCurrency": self.base_currency,
            "quoteCurrency": self.quote_currency,
        }


async def convert(
    session: AsyncSession,
    amount: Decimal,
    base: str,
    quote: str,
) -> ConvertedAmount:
    rate = await get_rate(session, base, quote)
    if rate is None:
        return ConvertedAmount(
            amount=amount,
            converted=amount,
            rate=None,
            is_converted=False,
            base_currency=base,
            quote_currency=quote,
        )
    converted = _round2(amount * rate)
    return ConvertedAmount(
        amount=amount,
        converted=converted,
        rate=rate,
        is_converted=(base != quote),
        base_currency=base,
        quote_currency=quote,
    )
