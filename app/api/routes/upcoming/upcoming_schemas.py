from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class UpcomingItem(BaseModel):
    type: str  # INCOME, EXPENSE, DEBT_EMI, INSURANCE_PREMIUM, PLAN_CONTRIB, GOAL_CONTRIB, AUTO_TRANSFER
    direction: str  # IN / OUT
    name: str
    amount: Decimal
    source_type: str
    source_id: UUID
    is_personal: bool = False
    date: datetime
    job_id: UUID | None = None
    source_endpoint: str | None = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UpcomingResponse(BaseModel):
    horizon_days: int
    items: list[UpcomingItem]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
