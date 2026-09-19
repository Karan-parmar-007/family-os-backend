from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SavingsLedgerEntryResponse(BaseModel):
    id: UUID
    pool_type: str
    family_id: UUID | None = None
    user_id: UUID | None = None
    amount: Decimal
    direction: str
    source_type: str
    source_id: UUID | None = None
    description: str | None = None
    document_id: UUID | None = None
    occurred_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class GlobalSavingsResponse(BaseModel):
    user_id: UUID
    origin_amount: Decimal
    total_savings: Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class GlobalSavingsOriginRequest(BaseModel):
    origin_amount: float = Field(..., gt=0, description="Standalone global opening balance")


class GlobalSavingsAdjustRequest(BaseModel):
    amount: float = Field(..., description="Positive to add, negative to subtract")


class GlobalSavingsMutationResponse(BaseModel):
    message: str
    total_savings: Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class GlobalPersonalEntryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0)
    direction: str = Field(default="OUT", pattern="^(IN|OUT)$")
    entry_date: datetime | None = None
    note: str | None = None


class GlobalPersonalEntryResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    amount: Decimal
    direction: str
    entry_date: datetime
    note: str | None = None
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class GlobalPersonalEntryListResponse(BaseModel):
    items: list[GlobalPersonalEntryResponse]
    total_savings: Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
