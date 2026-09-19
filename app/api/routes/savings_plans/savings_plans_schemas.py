from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse
from app.api.routes.investments.investment_schemas import SplitLineRequest


class SavingsPlanCreateRequest(BaseModel):
    plan_name: str = Field(..., min_length=1)
    target_amount: Decimal = Field(..., ge=0)
    scope_type: str = Field(default="FAMILY")
    access_level: str = Field(default="FAMILY")
    is_personal: bool = False
    # Sinking-fund / EMI config
    purpose_type: str | None = None
    linked_type: str | None = None
    linked_id: UUID | None = None
    target_frequency: str | None = None
    next_target_date: datetime | None = None
    contribution_amount: Decimal | None = Field(default=None, ge=0)
    contribution_every: str | None = None
    next_contribution_date: datetime | None = None
    auto_deduct: bool | None = None
    confirm_contributions: bool | None = None
    requires_confirmation: bool | None = None
    skip_fine_amount: Decimal | None = None
    emi_mode: str | None = None
    splitLines: list[SplitLineRequest] | None = None


class SavingsPlanUpdateRequest(BaseModel):
    plan_name: str | None = None
    target_amount: Decimal | None = Field(default=None, ge=0)
    accumulated_amount: Decimal | None = Field(default=None, ge=0)
    status: str | None = None
    purpose_type: str | None = None
    linked_type: str | None = None
    linked_id: UUID | None = None
    target_frequency: str | None = None
    next_target_date: datetime | None = None
    contribution_amount: Decimal | None = Field(default=None, ge=0)
    contribution_every: str | None = None
    next_contribution_date: datetime | None = None
    auto_deduct: bool | None = None
    confirm_contributions: bool | None = None
    requires_confirmation: bool | None = None
    skip_fine_amount: Decimal | None = None
    emi_mode: str | None = None
    splitLines: list[SplitLineRequest] | None = None


class SavingsPlanResponse(BaseModel):
    id: UUID
    family_id: UUID
    plan_name: str
    target_amount: Decimal
    accumulated_amount: Decimal
    scope_type: str
    status: str
    access_level: str
    is_personal: bool = False
    purpose_type: str | None = None
    linked_type: str | None = None
    linked_id: UUID | None = None
    target_frequency: str | None = None
    next_target_date: datetime | None = None
    contribution_amount: Decimal | None = None
    contribution_every: str | None = None
    next_contribution_date: datetime | None = None
    auto_deduct: bool | None = None
    confirm_contributions: bool = False
    requires_confirmation: bool = False
    skip_fine_amount: Decimal = Decimal("0")
    completed_at: datetime | None = None
    emi_mode: str = "FIXED"
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class SavingsPlanPrepayRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    mode: str | None = Field(
        default=None, description="CLEAR_UPCOMING or REDUCE_EMI"
    )
    contribution_date: datetime | None = None


class SavingsPlanPartPaymentRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    mode: str = Field(
        default="REDUCE_EMI",
        description="REDUCE_EMI or KEEP_EMI_REDUCE_TENURE",
    )
    splitLines: list[SplitLineRequest] | None = None
    paidExternally: bool = False


class SavingsPlanPayoutRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    note: str | None = None


class SavingsPlanDefaultEntryResponse(BaseModel):
    id: UUID
    reason: str
    amount: Decimal
    fineAmount: Decimal
    status: str
    periodKey: str
    settledAt: datetime | None = None
    createdAt: datetime


class SavingsPlanDefaultListResponse(BaseModel):
    items: list[SavingsPlanDefaultEntryResponse]
    totalOpen: Decimal


class SavingsPlanDefaultSettleRequest(BaseModel):
    splitLines: list[SplitLineRequest] | None = None
    note: str | None = None


class SavingsPlanDefaultWaiveRequest(BaseModel):
    note: str | None = None


class LinkCandidateResponse(BaseModel):
    id: UUID
    name: str
    amount: Decimal
    nextDate: datetime | None = None
    suggestedContribution: Decimal | None = None


class LinkCandidateListResponse(BaseModel):
    items: list[LinkCandidateResponse]


class SavingsPlanListResponse(PaginatedResponse[SavingsPlanResponse]):
    pass


class SavingsPlanContributionCreateRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    direction: str = Field(default="IN", pattern="^(IN|OUT)$")
    contribution_date: datetime | None = None


class SavingsPlanContributionResponse(BaseModel):
    id: UUID
    plan_id: UUID
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


class SavingsPlanContributionListResponse(BaseModel):
    items: list[SavingsPlanContributionResponse]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
