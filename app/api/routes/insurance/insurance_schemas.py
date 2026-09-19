from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse
from app.api.routes.investments.investment_schemas import SplitLineRequest


class InsuranceCreateRequest(BaseModel):
    insurance_name: str = Field(..., min_length=1)
    type: str
    provider: str | None = None
    policy_number: str | None = None
    insured_user_id: UUID | None = None
    nominee: str | None = None
    premium_amount: Decimal = Field(default=Decimal("0"), ge=0)
    coverage_amount: Decimal = Field(default=Decimal("0"), ge=0)
    premium_every: str | None = None
    next_premium_date: datetime | None = None
    emi_count: int | None = Field(default=None, ge=1)
    let_everyone_edit: bool = True
    start_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    requires_confirmation: bool = False
    bounce_fine_amount: Decimal = Decimal("0")
    allow_auto_lapse: bool = False
    document_id: UUID | None = None
    scope_type: str = Field(default="FAMILY")
    access_level: str = Field(default="FAMILY")
    is_personal: bool = False
    splitLines: list[SplitLineRequest] | None = None


class InsuranceUpdateRequest(BaseModel):
    insurance_name: str | None = None
    provider: str | None = None
    policy_number: str | None = None
    insured_user_id: UUID | None = None
    nominee: str | None = None
    premium_amount: Decimal | None = Field(default=None, ge=0)
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    premium_every: str | None = None
    next_premium_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    requires_confirmation: bool | None = None
    bounce_fine_amount: Decimal | None = None
    allow_auto_lapse: bool | None = None
    status: str | None = None
    access_level: str | None = None
    splitLines: list[SplitLineRequest] | None = None


class InsuranceResponse(BaseModel):
    id: UUID
    family_id: UUID
    insurance_name: str
    type: str
    provider: str | None = None
    policy_number: str | None = None
    insured_member: UUID | None = None
    insured_user_id: UUID | None = None
    nominee: str | None = None
    premium_amount: Decimal
    coverage_amount: Decimal
    premium_every: str | None = None
    next_premium_date: datetime | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    requires_confirmation: bool = True
    bounce_fine_amount: Decimal = Decimal("0")
    allow_auto_lapse: bool = True
    completed_at: datetime | None = None
    scope_type: str
    status: str
    access_level: str
    is_personal: bool = False
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class InsuranceListResponse(PaginatedResponse[InsuranceResponse]):
    pass


class InsurancePayNowRequest(BaseModel):
    splitLines: list[SplitLineRequest] | None = None
    paidExternally: bool = False


class InsuranceSplitPlanRequest(BaseModel):
    splitLines: list[SplitLineRequest]
