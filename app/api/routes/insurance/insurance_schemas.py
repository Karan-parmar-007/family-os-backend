from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse

_camel = ConfigDict(alias_generator=to_camel, populate_by_name=True)

ScheduleMode = Literal["NONE", "INTERVAL", "CUSTOM"]
IntervalFrequency = Literal["MONTHLY", "QUARTERLY", "HALF_YEARLY", "YEARLY"]


class InstallmentInput(BaseModel):
    due_date: datetime
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)

    model_config = _camel


class _ScheduleFields(BaseModel):
    """INTERVAL: annual_premium is split evenly across the year (last payment of
    each year absorbs rounding), starting at next_premium_date.
    CUSTOM: each installment has its own date and amount.
    NONE: nothing is charged automatically."""

    schedule_mode: ScheduleMode | None = None
    annual_premium: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    premium_every: IntervalFrequency | None = None
    next_premium_date: datetime | None = None
    installments: list[InstallmentInput] | None = Field(default=None, max_length=240)

    def check_schedule(self) -> None:
        if self.schedule_mode == "INTERVAL":
            missing = [
                name
                for name, value in (
                    ("annualPremium", self.annual_premium),
                    ("premiumEvery", self.premium_every),
                    ("nextPremiumDate", self.next_premium_date),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"Interval schedule needs: {', '.join(missing)}")
        if self.schedule_mode == "CUSTOM":
            if not self.installments:
                raise ValueError("Add at least one installment date")
            dates = [i.due_date.date() for i in self.installments]
            if len(set(dates)) != len(dates):
                raise ValueError("Two installments cannot share the same date")


class InsuranceCreateRequest(_ScheduleFields):
    insurance_name: str = Field(..., min_length=1, max_length=255)
    type: str | None = Field(default=None, max_length=64)
    category_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=255)
    policy_number: str | None = Field(default=None, max_length=128)
    insured_user_id: UUID | None = None
    nominee: str | None = Field(default=None, max_length=255)
    premium_amount: Decimal = Field(default=Decimal("0"), ge=0)
    coverage_amount: Decimal = Field(default=Decimal("0"), ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    document_id: UUID | None = None
    access_level: str = Field(default="FAMILY")
    let_everyone_edit: bool = False
    is_personal: bool = False
    schedule_mode: ScheduleMode = "NONE"

    model_config = _camel

    @model_validator(mode="after")
    def _validate(self) -> "InsuranceCreateRequest":
        self.check_schedule()
        return self


class InsuranceUpdateRequest(_ScheduleFields):
    insurance_name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: UUID | None = None
    provider: str | None = None
    policy_number: str | None = None
    insured_user_id: UUID | None = None
    nominee: str | None = None
    premium_amount: Decimal | None = Field(default=None, ge=0)
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    document_id: UUID | None = None
    status: Literal["ACTIVE", "LAPSED", "MATURED", "CLAIMED"] | None = None
    access_level: str | None = None
    let_everyone_edit: bool | None = None

    model_config = _camel

    @model_validator(mode="after")
    def _validate(self) -> "InsuranceUpdateRequest":
        self.check_schedule()
        return self


class InstallmentResponse(BaseModel):
    id: UUID
    due_at: datetime
    amount: Decimal
    status: str
    paid_at: datetime | None = None
    paid_event_id: UUID | None = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class InsuranceResponse(BaseModel):
    id: UUID
    family_id: UUID
    insurance_name: str
    type: str
    category_id: UUID | None = None
    provider: str | None = None
    policy_number: str | None = None
    insured_member: UUID | None = None
    insured_user_id: UUID | None = None
    nominee: str | None = None
    premium_amount: Decimal
    coverage_amount: Decimal
    schedule_mode: str = "NONE"
    annual_premium: Decimal | None = None
    premium_every: str | None = None
    next_premium_date: datetime | None = None
    next_installment_amount: Decimal | None = None
    paid_count: int = 0
    pending_count: int = 0
    start_date: datetime | None = None
    end_date: datetime | None = None
    maturity_date: datetime | None = None
    maturity_amount: Decimal | None = None
    document_id: UUID | None = None
    scope_type: str
    status: str
    access_level: str
    user_id: UUID | None = None
    created_by: UUID | None = None
    let_everyone_edit: bool = False
    can_edit: bool = False
    is_personal: bool = False
    installments: list[InstallmentResponse] | None = None
    created_at: datetime

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class InsuranceListResponse(PaginatedResponse[InsuranceResponse]):
    model_config = _camel
