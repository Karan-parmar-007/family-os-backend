from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class CategoryCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    category_type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = None
    icon: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class CategoryResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    category_type: str
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class CategoryListResponse(BaseModel):
    items: List[CategoryResponse]
    total: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
