from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import PaginatedResponse


class HistoryItem(BaseModel):
    entity_type: str
    id: UUID
    name: str
    headline: str
    completed_at: datetime
    terminal_status: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HistoryListResponse(PaginatedResponse[HistoryItem]):
    pass
