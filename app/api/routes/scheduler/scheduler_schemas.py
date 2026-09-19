from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse


class ScheduledJobResponse(BaseModel):
    id: UUID
    family_id: UUID
    job_type: str
    source_type: str
    source_id: UUID
    assigned_user_id: UUID | None = None
    amount: Decimal
    direction: str
    period_key: str
    scheduled_for: datetime
    requires_confirmation: bool
    status: str
    attempt_count: int
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ScheduledJobListResponse(PaginatedResponse[ScheduledJobResponse]):
    pass


class JobActionRequest(BaseModel):
    action: str
    delay_days: int | None = Field(default=None, ge=1, le=90)
    payload: dict | None = None

