import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse


class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    family_id: UUID | None = None
    type: str
    title: str
    body: str | None = None
    related_job_id: UUID | None = None
    related_entity_type: str | None = None
    related_entity_id: UUID | None = None
    allowed_actions: list[str]
    meta: dict[str, Any] | None = None
    status: str
    action_taken: str | None = None
    actioned_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    @classmethod
    def from_model(cls, n: Any) -> "NotificationResponse":
        actions = n.allowed_actions
        if isinstance(actions, dict):
            actions = actions.get("actions", [])
        if not isinstance(actions, list):
            actions = list(actions) if actions else []
        data = {**n.model_dump(), "allowed_actions": actions}
        return cls.model_validate(data)


class NotificationListResponse(PaginatedResponse[NotificationResponse]):
    pass


class UnreadCountResponse(BaseModel):
    count: int
    actionable_count: int = 0

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SplitLinePayload(BaseModel):
    """One pool line in an ACCEPT_WITH_SPLITS or default-settlement payload."""

    pool_type: str  # CURRENT_FAMILY | PERSONAL | OTHER_FAMILY
    family_id: UUID | None = None
    user_id: UUID | None = None
    amount: str  # string to avoid float precision issues; service parses to Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class IncomeAllocationPayload(BaseModel):
    """One family allocation in an ADJUST_AMOUNT income payload."""

    family_id: UUID
    amount: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class NotificationActionPayload(BaseModel):
    """Optional payload for actions that require extra data."""

    new_amount: str | None = None
    split_lines: list[SplitLinePayload] | None = None
    income_allocations: list[IncomeAllocationPayload] | None = None
    personal_amount: str | None = None
    expense_sources: list[SplitLinePayload] | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class NotificationActionRequest(BaseModel):
    action: str
    delay_days: int | None = Field(default=None, ge=1, le=90)
    payload: NotificationActionPayload | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MessageResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
