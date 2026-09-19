from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class AdminUserFamilyItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: UUID
    name: str
    is_family_manager: bool
    joined_at: datetime


class AdminUserSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    sso_user_id: str
    email: str
    display_name: str
    personal_currency: str
    timezone: str
    personal_code: str
    max_family_memberships: int
    family_count: int
    families: List[AdminUserFamilyItem]
    created_at: datetime


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    items: List[AdminUserSummary]


class AdminUserUpdateCapRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    max_family_memberships: int

    @field_validator("max_family_memberships")
    @classmethod
    def validate_cap(cls, v: int) -> int:
        if v < 1:
            raise ValueError("maxFamilyMemberships must be at least 1")
        if v > 100:
            raise ValueError("maxFamilyMemberships cannot exceed 100")
        return v


class AdminFamilySummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    name: str
    currency: str
    timezone: str
    member_count: int
    head_name: Optional[str] = None
    created_at: datetime


class AdminFamilyListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    items: List[AdminFamilySummary]
