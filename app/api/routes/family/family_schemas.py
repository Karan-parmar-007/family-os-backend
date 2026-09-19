from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from pydantic.alias_generators import to_camel


# -----------------------------------------------
# Request Schemas
# -----------------------------------------------

class FamilyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Name of the family")
    currency: str = Field(default="USD", max_length=3, description="Currency code (e.g., USD, INR)")
    timezone: str = Field(default="Asia/Kolkata", max_length=64, description="Timezone name")
    origin_amount: float = Field(..., ge=1.0, description="Initial pool balance in creator currency (>= 1)")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    currency: Optional[str] = Field(default=None, max_length=3)
    timezone: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyJoinRequestCreate(BaseModel):
    membership_code: str = Field(..., min_length=8, max_length=8, description="8-digit family membership code")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyInviteCreateRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address to invite")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# -----------------------------------------------
# Response Schemas
# -----------------------------------------------

class FamilySummaryResponse(BaseModel):
    id: UUID
    name: str
    currency: str
    timezone: str
    is_manager: bool
    membership_code: str
    link_code: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyListResponse(BaseModel):
    items: List[FamilySummaryResponse]
    membership_count: int
    max_family_memberships: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyCreateResponse(BaseModel):
    message: str
    id: UUID
    name: str
    currency: str
    timezone: str
    membership_code: str
    link_code: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyUpdateResponse(BaseModel):
    id: UUID
    name: str
    currency: str
    timezone: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyMemberResponse(BaseModel):
    id: UUID
    email: str
    name: str
    is_family_manager: bool
    joined_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyMemberListResponse(BaseModel):
    items: List[FamilyMemberResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyTotalSavingsResponse(BaseModel):
    family_id: UUID
    total_savings: Optional[float] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyJoinRequestItemResponse(BaseModel):
    id: UUID
    family_id: UUID
    user_id: UUID
    user_name: str
    user_email: str
    status: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyJoinRequestListResponse(BaseModel):
    items: List[FamilyJoinRequestItemResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyJoinRequestActionResponse(BaseModel):
    message: str
    id: UUID
    status: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyInviteResponse(BaseModel):
    id: UUID
    family_id: UUID
    email: str
    token: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyInviteDetailResponse(BaseModel):
    id: UUID
    family_name: str
    invited_by_email: str
    email: str
    status: str
    expires_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
