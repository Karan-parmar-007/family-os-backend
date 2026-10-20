from datetime import datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import CamelPaginatedResponse

CATEGORY_TYPES = (
    "INCOME",
    "EXPENSE",
    "DEBT",
    "ASSET",
    "INSURANCE",
    "VAULT_PASSWORD",
    "VAULT_DOCUMENT",
)


class CategoryCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY")  # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    category_type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = Field(default=None, max_length=32)
    icon: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    color: Optional[str] = Field(default=None, max_length=32)
    icon: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CategoryResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    category_type: str
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    can_edit: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class CategoryListResponse(CamelPaginatedResponse[CategoryResponse]):
    pass
