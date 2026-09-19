from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class TransferCreateRequest(BaseModel):
    to_family_id: UUID | None = None
    to_user_id: UUID | None = None
    from_scope: str = "FAMILY"
    to_scope: str = "FAMILY"
    from_user_id: UUID | None = None
    entity_type: str = Field(default="SAVINGS")
    amount: Decimal = Field(..., gt=0)
    note: str | None = None
    dest_link_code: str | None = None
    dest_personal_code: str | None = None
    is_recurring: bool = False
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    requires_confirmation: bool = True
    show_breakdown_to_receiver: bool = True

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def validate_scopes(self) -> "TransferCreateRequest":
        if self.from_scope not in {"FAMILY", "PERSONAL"}:
            raise ValueError("from_scope must be FAMILY or PERSONAL")
        if self.to_scope not in {"FAMILY", "PERSONAL"}:
            raise ValueError("to_scope must be FAMILY or PERSONAL")
        if self.to_scope == "FAMILY" and self.to_family_id is None and not self.dest_link_code:
            raise ValueError("to_family_id or dest_link_code is required when to_scope is FAMILY")
        if self.to_scope == "PERSONAL" and self.to_user_id is None and not self.dest_personal_code:
            raise ValueError("to_user_id or dest_personal_code is required when to_scope is PERSONAL")
        return self


class TransferUpdateRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = None
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    requires_confirmation: bool | None = None
    show_breakdown_to_receiver: bool | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TransferResponse(BaseModel):
    id: UUID
    family_id: UUID | None = None
    to_family_id: UUID | None = None
    from_scope: str
    to_scope: str
    from_user_id: UUID | None = None
    to_user_id: UUID | None = None
    entity_type: str
    amount: Decimal
    note: str | None = None
    status: str
    is_recurring: bool
    recurring_every: str | None = None
    next_run_date: datetime | None = None
    end_date: datetime | None = None
    requires_confirmation: bool = True
    show_breakdown_to_receiver: bool = True
    direction: str | None = None
    created_by: UUID
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class TransferListResponse(BaseModel):
    items: list[TransferResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TransferDetailResponse(TransferResponse):
    pass
