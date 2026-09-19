from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse


class GoalCreateRequest(BaseModel):
    goal_name: str = Field(..., min_length=1)
    target_amount: Decimal = Field(..., ge=0)
    scope_type: str = Field(default="FAMILY")
    access_level: str = Field(default="FAMILY")
    notes: str | None = None
    document_id: UUID | None = None
    is_personal: bool = False


class GoalUpdateRequest(BaseModel):
    goal_name: str | None = None
    target_amount: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    status: str | None = None


class GoalResponse(BaseModel):
    id: UUID
    family_id: UUID
    goal_name: str
    target_amount: Decimal
    collected_amount: Decimal
    scope_type: str
    status: str
    access_level: str
    notes: str | None = None
    completed_at: datetime | None = None
    is_personal: bool = False
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class GoalListResponse(PaginatedResponse[GoalResponse]):
    pass


class GoalContributionCreateRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    note: str | None = None
    contribution_date: datetime | None = None


class GoalWithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    note: str | None = None


class GoalContributionResponse(BaseModel):
    id: UUID
    goal_id: UUID
    family_id: UUID
    amount: Decimal
    direction: str
    contribution_date: datetime
    source_type: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class GoalContributionListResponse(BaseModel):
    items: list[GoalContributionResponse]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
