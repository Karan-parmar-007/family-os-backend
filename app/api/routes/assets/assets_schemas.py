from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse

ASSET_TYPES = [
    "HOME", "LAND", "APARTMENT", "CAR", "BIKE", "GOLD", "SILVER", "JEWELRY",
    "ELECTRONICS", "FURNITURE", "APPLIANCE", "ART", "COLLECTIBLE", "LIVESTOCK",
    "MACHINERY", "OTHER",
]


class AssetCreateRequest(BaseModel):
    asset_name: str = Field(..., min_length=1)
    type: str
    scope_type: str = Field(default="FAMILY")
    value: Decimal = Field(default=Decimal("0"), ge=0)
    quantity: Decimal | None = Field(default=None, ge=0)
    quantity_label: str | None = None
    acquired_on: date | None = None
    notes: str | None = None
    document_id: UUID | None = None
    in_someone_name: UUID | None = None
    access_level: str = Field(default="FAMILY")
    is_personal: bool = False

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AssetUpdateRequest(BaseModel):
    asset_name: str | None = None
    type: str | None = None
    value: Decimal | None = Field(default=None, ge=0)
    quantity: Decimal | None = Field(default=None, ge=0)
    quantity_label: str | None = None
    acquired_on: date | None = None
    notes: str | None = None
    document_id: UUID | None = None
    in_someone_name: UUID | None = None
    access_level: str | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class AssetResponse(BaseModel):
    id: UUID
    family_id: UUID
    asset_name: str
    type: str
    scope_type: str
    value: Decimal
    quantity: Decimal | None = None
    quantity_label: str | None = None
    acquired_on: date | None = None
    notes: str | None = None
    document_id: UUID | None = None
    in_someone_name: UUID | None = None
    access_level: str
    is_personal: bool = False
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class AssetListResponse(PaginatedResponse[AssetResponse]):
    total_value: Decimal = Decimal("0")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

