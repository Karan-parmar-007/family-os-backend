from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class FosCurrencyResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    code: str
    name: str
    symbol: str
    rate_to_usd: Decimal
    logo_key: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FosCurrencyListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    items: List[FosCurrencyResponse]


class CurrencyCreateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str
    name: str
    symbol: str
    rate_to_usd: Decimal
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("Currency code must be exactly 3 uppercase letters (ISO 4217)")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v

    @field_validator("rate_to_usd")
    @classmethod
    def validate_rate(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("rateToUsd must be greater than 0")
        return v


class CurrencyUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: Optional[str] = None
    symbol: Optional[str] = None
    rate_to_usd: Optional[Decimal] = None
    is_active: Optional[bool] = None

    @field_validator("rate_to_usd")
    @classmethod
    def validate_rate(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("rateToUsd must be greater than 0")
        return v


# Legacy schemas
class CurrencyRateCreate(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_from: datetime


class CurrencyRateUpdate(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    rate: Decimal
    effective_from: datetime


class CurrencyRateResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: UUID
    base_currency: str
    quote_currency: str
    rate: Decimal
    status: str
    effective_from: datetime
    finalized_by: Optional[UUID] = None
    finalized_at: Optional[datetime] = None
    created_at: datetime


class CurrencyRateListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    items: List[CurrencyRateResponse]
