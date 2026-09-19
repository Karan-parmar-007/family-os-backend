from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse
from app.api.schemas.funding import FundingSourceInput


class ExpenseCategoryCreateRequest(BaseModel):
    category_name: str = Field(..., min_length=1, max_length=255)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ExpenseCategoryResponse(BaseModel):
    id: UUID
    family_id: UUID
    category_name: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ExpenseCategoryListResponse(BaseModel):
    items: list[ExpenseCategoryResponse]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ExpenseLogCreateRequest(BaseModel):
    expense_name: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    expense_date: datetime
    category_id: UUID | None = None
    scope_type: str = Field(default="FAMILY")
    is_personal: bool = False
    access_level: str = Field(default="FAMILY")
    funding_sources: list[FundingSourceInput] | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None


class ExpenseLogUpdateRequest(BaseModel):
    expense_name: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    expense_date: datetime | None = None
    category_id: UUID | None = None
    access_level: str | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None


class ExpenseLogResponse(BaseModel):
    id: UUID
    family_id: UUID
    scope_type: str
    logged_by: UUID
    expense_name: str
    amount: Decimal
    category_id: UUID | None = None
    expense_date: datetime
    source_type: str
    access_level: str
    created_at: datetime
    is_personal: bool = False
    user_id: UUID | None = None
    expense_made_for_user_id: UUID | None = None
    added_by_user_id: UUID | None = None

    @computed_field
    def entry_done_by(self) -> UUID | None:
        return self.added_by_user_id or self.logged_by

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ExpenseLogListResponse(PaginatedResponse[ExpenseLogResponse]):
    pass


class ExpenseRecurringCreateRequest(BaseModel):
    expense_name: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    category_id: UUID | None = None
    scope_type: str = Field(default="FAMILY")
    is_personal: bool = False
    paid_every: str = Field(..., min_length=1)
    next_payment_date: datetime
    access_level: str | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None


class ExpenseRecurringUpdateRequest(BaseModel):
    expense_name: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    category_id: UUID | None = None
    paid_every: str | None = None
    next_payment_date: datetime | None = None
    access_level: str | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None


class ExpenseRecurringResponse(BaseModel):
    id: UUID
    family_id: UUID
    scope_type: str
    expense_name: str
    amount: Decimal
    category_id: UUID | None = None
    is_recurring: bool
    paid_every: str | None = None
    next_payment_date: datetime | None = None
    access_level: str
    is_personal: bool = False
    user_id: UUID | None = None
    expense_made_for_user_id: UUID | None = None
    added_by_user_id: UUID | None = None
    created_at: datetime

    @computed_field
    def entry_done_by(self) -> UUID | None:
        return self.added_by_user_id or self.user_id

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ExpenseRecurringListResponse(PaginatedResponse[ExpenseRecurringResponse]):
    pass
