from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse
from app.api.routes.investments.investment_schemas import SplitLineRequest
from app.api.routes.debt.debt_validation import (
    normalize_emi_fields,
    normalize_interest_fields,
    validate_debt_type,
    validate_mask_fields,
)


class ScopeViewItem(BaseModel):
    id: UUID | None = None
    scope_kind: str
    family_id: UUID | None = None
    user_id: UUID | None = None
    is_primary: bool = False
    display_name: str | None = None
    display_type: str | None = None
    display_total_amount: Decimal | None = None
    display_remaining_amount: Decimal | None = None
    display_emi_amount: Decimal | None = None
    display_interest_rate: float | None = None
    is_masked: bool = False
    show_breakdown: bool = False
    access_level: str | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ScopeViewListResponse(BaseModel):
    items: list[ScopeViewItem]


class ScopeViewUpsertRequest(BaseModel):
    views: list[ScopeViewItem] | None = None
    scope_views: list[ScopeViewItem] | None = Field(default=None, alias="scopeViews")

    model_config = ConfigDict(populate_by_name=True)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    def resolved_views(self) -> list[ScopeViewItem]:
        return self.views or self.scope_views or []


class DebtCreateRequest(BaseModel):
    debt_name: str = Field(..., min_length=1)
    type: str
    is_personal: bool = False
    debt_in_the_name_of: UUID | None = None  # family debts only; defaults to creator

    total_amount: Decimal = Field(..., ge=0)
    remaining_amount: Decimal | None = None

    has_interest: bool = False
    interest_type: str | None = None
    interest_rate: float | None = None
    compounding_frequency: str | None = None
    fixed_fee_amount: Decimal | None = None
    interest_increase_every: str | None = None
    interest_increase_percentage: float | None = None
    next_interest_increase_date: datetime | None = None

    has_emi: bool = False
    emi_amount: Decimal | None = None
    emi_every: str | None = "MONTHLY"
    # Custom interval – mutually exclusive with emi_every
    emi_interval_days: int | None = None
    emi_interval_months: int | None = None
    emi_interval_years: int | None = None
    tenure_months: int | None = None
    emi_next_date: datetime | None = None
    requires_confirmation: bool = True

    bounce_fine_amount: Decimal = Decimal("0")
    allow_auto_default: bool = True

    is_masked: bool = False
    real_total_amount: Decimal | None = None
    real_remaining_amount: Decimal | None = None
    real_emi_amount: Decimal | None = None
    real_interest_rate: float | None = None
    show_split_to_family: bool = False

    start_date: datetime | None = None
    end_date: datetime | None = None
    document_id: UUID | None = None
    access_level: str | None = None
    show_doc_to_all: bool = True
    doc_viewer_user_ids: list[UUID] | None = None

    splitLines: list[SplitLineRequest] | None = None
    showSplitToFamily: bool | None = None
    scope_views: list[ScopeViewItem] | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def _validate_debt_create(self) -> "DebtCreateRequest":
        validate_debt_type(self.type)
        is_personal = bool(self.is_personal)
        is_masked = bool(self.is_masked) and not is_personal

        if is_masked:
            if self.real_total_amount is None:
                raise ValueError("real_total_amount is required when is_masked")
            display_total = self.total_amount
            display_remaining = (
                self.remaining_amount
                if self.remaining_amount is not None
                else self.total_amount
            )
            validate_mask_fields(
                is_masked=True,
                display_total=display_total,
                display_remaining=display_remaining,
                display_emi=self.emi_amount,
                display_rate=self.interest_rate,
                has_emi=self.has_emi,
                has_interest=self.has_interest,
            )
            principal = (
                self.real_remaining_amount
                if self.real_remaining_amount is not None
                else self.real_total_amount
            )
            interest = normalize_interest_fields(
                has_interest=self.has_interest,
                interest_type=self.interest_type,
                interest_rate=(
                    self.real_interest_rate
                    if self.real_interest_rate is not None
                    else self.interest_rate
                ),
                compounding_frequency=self.compounding_frequency,
                fixed_fee_amount=self.fixed_fee_amount,
                interest_increase_every=self.interest_increase_every,
                interest_increase_percentage=self.interest_increase_percentage,
                next_interest_increase_date=self.next_interest_increase_date,
            )
            normalize_emi_fields(
                has_emi=self.has_emi,
                principal=principal,
                has_interest=interest["has_interest"],
                interest_type=interest["interest_type"],
                interest_rate=interest["interest_rate"],
                compounding_frequency=interest["compounding_frequency"],
                emi_amount=self.real_emi_amount or self.emi_amount,
                emi_every=self.emi_every,
                tenure_months=self.tenure_months,
                emi_next_date=self.emi_next_date,
                requires_confirmation=self.requires_confirmation,
            )
        else:
            principal = (
                self.remaining_amount
                if self.remaining_amount is not None
                else self.total_amount
            )
            interest = normalize_interest_fields(
                has_interest=self.has_interest,
                interest_type=self.interest_type,
                interest_rate=self.interest_rate,
                compounding_frequency=self.compounding_frequency,
                fixed_fee_amount=self.fixed_fee_amount,
                interest_increase_every=self.interest_increase_every,
                interest_increase_percentage=self.interest_increase_percentage,
                next_interest_increase_date=self.next_interest_increase_date,
            )
            normalize_emi_fields(
                has_emi=self.has_emi,
                principal=principal,
                has_interest=interest["has_interest"],
                interest_type=interest["interest_type"],
                interest_rate=interest["interest_rate"],
                compounding_frequency=interest["compounding_frequency"],
                emi_amount=self.emi_amount,
                emi_every=self.emi_every,
                tenure_months=self.tenure_months,
                emi_next_date=self.emi_next_date,
                requires_confirmation=self.requires_confirmation,
            )
        return self


class DebtUpdateRequest(BaseModel):
    debt_name: str | None = None
    status: str | None = None
    total_amount: Decimal | None = None
    remaining_amount: Decimal | None = None

    has_interest: bool | None = None
    interest_type: str | None = None
    interest_rate: float | None = None
    compounding_frequency: str | None = None
    fixed_fee_amount: Decimal | None = None
    interest_increase_every: str | None = None
    interest_increase_percentage: float | None = None
    next_interest_increase_date: datetime | None = None

    has_emi: bool | None = None
    emi_amount: Decimal | None = None
    emi_every: str | None = None
    emi_interval_days: int | None = None
    emi_interval_months: int | None = None
    emi_interval_years: int | None = None
    tenure_months: int | None = None
    emi_next_date: datetime | None = None
    requires_confirmation: bool | None = None

    bounce_fine_amount: Decimal | None = None
    allow_auto_default: bool | None = None

    is_masked: bool | None = None
    real_total_amount: Decimal | None = None
    real_remaining_amount: Decimal | None = None
    real_emi_amount: Decimal | None = None
    real_interest_rate: float | None = None
    show_split_to_family: bool | None = None

    end_date: datetime | None = None
    access_level: str | None = None
    show_doc_to_all: bool | None = None
    doc_viewer_user_ids: list[UUID] | None = None

    splitLines: list[SplitLineRequest] | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DebtQuoteRequest(BaseModel):
    principal: Decimal = Field(..., gt=0)
    interest_type: str
    annual_rate_pct: float | None = None
    compounding_frequency: str = "MONTHLY"
    emi_amount: Decimal | None = Field(default=None, gt=0)
    tenure_months: int | None = Field(default=None, gt=0)
    fixed_fee_amount: Decimal | None = Field(default=None, ge=0)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DebtResponse(BaseModel):
    id: UUID
    family_id: UUID
    scope_type: str
    debt_name: str
    type: str
    status: str
    debt_in_the_name_of: UUID
    is_personal: bool = False

    total_amount: Decimal
    remaining_amount: Decimal
    total_paid: Decimal = Decimal("0")

    has_interest: bool = False
    interest_type: str | None = None
    interest_rate: float | None = None
    compounding_frequency: str | None = None
    fixed_fee_amount: Decimal | None = None
    interest_increase_every: str | None = None
    interest_increase_percentage: float | None = None
    next_interest_increase_date: datetime | None = None

    has_emi: bool = False
    emi_amount: Decimal | None = None
    emi_every: str | None = None
    tenure_months: int | None = None
    emi_next_date: datetime | None = None
    requires_confirmation: bool = True

    bounce_fine_amount: Decimal = Decimal("0")
    allow_auto_default: bool = True

    is_masked: bool = False
    show_split_to_family: bool = False
    real: dict | None = None

    start_date: datetime | None = None
    end_date: datetime | None = None
    completed_at: datetime | None = None
    document_id: UUID | None = None
    access_level: str
    show_doc_to_all: bool = True
    doc_viewer_user_ids: list[UUID] | None = None
    created_at: datetime

    show_breakdown: bool = False
    view_id: UUID | None = None
    scope_views: list[ScopeViewItem] | None = None
    balance_for_part_payment: Decimal = Decimal("0")
    split_lines: list[SplitLineRequest] | None = None
    my_emi_amount: Decimal | None = None
    my_obligation_remaining: Decimal | None = None
    my_expected_total: Decimal | None = None
    can_contribute: bool = False
    is_owner: bool = False
    can_part_payment: bool = False

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class DebtListResponse(PaginatedResponse[DebtResponse]):
    pass


PartPaymentModeLiteral = Literal[
    "REDUCE_EMI",
    "REDUCE_TENURE",
    "CLEAR_UPCOMING",
    "ADVANCE_INSTALLMENTS",
    "REDUCE_BOTH",
    "FORECLOSURE",
]


class PartPaymentRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    mode: PartPaymentModeLiteral = Field(
        default="REDUCE_TENURE",
        description="REDUCE_EMI, REDUCE_TENURE, CLEAR_UPCOMING, ADVANCE_INSTALLMENTS, REDUCE_BOTH, FORECLOSURE",
    )
    splitLines: list[SplitLineRequest] | None = None
    paidExternally: bool = False
    targetEmi: Decimal | None = None
    targetTenure: int | None = None
    underpaymentPolicy: str | None = None
    overpaymentPolicy: str | None = None
    useBalance: bool = False
    reassignments: list[SplitLineRequest] | None = None


class ContributionRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    poolType: str | None = None
    familyId: UUID | None = None
    userId: UUID | None = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ContributionResponse(BaseModel):
    amount: Decimal
    balanceForPartPayment: Decimal
    obligationRemaining: Decimal | None = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PartPaymentResponse(BaseModel):
    oldRemaining: Decimal
    newRemaining: Decimal
    oldEmi: Decimal
    newEmi: Decimal
    newPeriods: int
    note: str
    interestSavedEstimate: Decimal | None = None
    payoffDate: datetime | None = None


class PartPaymentSimulateResponse(BaseModel):
    oldRemaining: Decimal
    newRemaining: Decimal
    oldEmi: Decimal
    newEmi: Decimal
    newPeriods: int
    note: str
    interestSavedEstimate: Decimal = Decimal("0")
    payoffDate: datetime | None = None
    periodsCleared: int = 0
    emiNextDate: datetime | None = None
    endDate: datetime | None = None


class PaymentAllocationResponse(BaseModel):
    poolType: str
    familyId: UUID | None = None
    userId: UUID | None = None
    amount: Decimal


class PaymentEventResponse(BaseModel):
    id: UUID
    debtId: UUID
    eventType: str
    periodKey: str | None = None
    scheduledAmount: Decimal | None = None
    actualAmount: Decimal
    principalAmount: Decimal = Decimal("0")
    interestAmount: Decimal = Decimal("0")
    feeAmount: Decimal = Decimal("0")
    paidAt: datetime
    status: str
    paidExternally: bool = False
    note: str | None = None
    jobId: UUID | None = None
    partPaymentMode: str | None = None
    underpaymentPolicy: str | None = None
    overpaymentPolicy: str | None = None
    createdAt: datetime
    allocations: list[PaymentAllocationResponse] = Field(default_factory=list)


class PaymentEventListResponse(BaseModel):
    items: list[PaymentEventResponse]


class DefaultEntryResponse(BaseModel):
    id: UUID
    reason: str
    amount: Decimal
    fineAmount: Decimal
    status: str
    periodKey: str
    settledAt: datetime | None = None
    createdAt: datetime


class DefaultListResponse(BaseModel):
    items: list[DefaultEntryResponse]
    totalOpen: Decimal


class DefaultSettleRequest(BaseModel):
    splitLines: list[SplitLineRequest] | None = None
    note: str | None = None


class DefaultWaiveRequest(BaseModel):
    note: str | None = None


class SplitPlanRequest(BaseModel):
    splitLines: list[SplitLineRequest]
