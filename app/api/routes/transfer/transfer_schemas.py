from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import CamelPaginatedResponse

_camel = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TransferCreateRequest(BaseModel):
    """Destination is either a direct id (own family, connected family, member,
    friend) or a code. Direct transfers complete immediately; code transfers
    wait for the receiver to accept, unless the code resolves to a direct
    destination."""

    to_family_id: UUID | None = None
    to_user_id: UUID | None = None
    from_scope: str = "FAMILY"
    to_scope: str = "FAMILY"
    from_user_id: UUID | None = None
    entity_type: str = Field(default="SAVINGS")
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)
    dest_link_code: str | None = Field(default=None, max_length=32)
    dest_personal_code: str | None = Field(default=None, max_length=32)
    is_recurring: bool = False
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    show_breakdown_to_receiver: bool = True
    idempotency_key: str | None = Field(default=None, max_length=64)

    model_config = _camel

    @model_validator(mode="after")
    def validate_scopes(self) -> "TransferCreateRequest":
        self.from_scope = (self.from_scope or "FAMILY").upper()
        self.to_scope = (self.to_scope or "FAMILY").upper()
        if self.from_scope not in {"FAMILY", "PERSONAL"}:
            raise ValueError("from_scope must be FAMILY or PERSONAL")
        if self.to_scope not in {"FAMILY", "PERSONAL"}:
            raise ValueError("to_scope must be FAMILY or PERSONAL")
        if self.to_scope == "FAMILY" and self.to_family_id is None and not self.dest_link_code:
            raise ValueError("Pick a family or enter its link code")
        if self.to_scope == "PERSONAL" and self.to_user_id is None and not self.dest_personal_code:
            raise ValueError("Pick a person or enter their personal code")
        if self.is_recurring and (not self.recurring_every or self.next_run_date is None):
            raise ValueError("Recurring transfers need an interval and a first date")
        return self


class TransferUpdateRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = None
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    show_breakdown_to_receiver: bool | None = None

    model_config = _camel


class TransferResponse(BaseModel):
    id: UUID
    family_id: UUID | None = None
    to_family_id: UUID | None = None
    from_scope: str
    to_scope: str
    from_user_id: UUID | None = None
    to_user_id: UUID | None = None
    from_label: str | None = None
    to_label: str | None = None
    entity_type: str
    amount: Decimal
    note: str | None = None
    status: str
    via_code: bool = False
    is_recurring: bool
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    requires_confirmation: bool = False
    show_breakdown_to_receiver: bool = True
    parent_id: UUID | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    direction: str | None = None
    can_accept: bool = False
    can_cancel: bool = False
    created_by: UUID
    created_at: datetime

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class TransferListResponse(CamelPaginatedResponse[TransferResponse]):
    pass


class TransferDetailResponse(TransferResponse):
    pass


class CodeLookupResponse(BaseModel):
    """Who a code belongs to, and whether a transfer to it is instant."""

    kind: Literal["FAMILY", "PERSON"]
    id: UUID
    name: str
    instant: bool

    model_config = _camel
