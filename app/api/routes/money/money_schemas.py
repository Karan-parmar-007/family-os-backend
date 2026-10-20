from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import CamelPaginatedResponse

_camel = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PartyInput(BaseModel):
    party_type: str = Field(default="FAMILY")  # MEMBER | FAMILY
    user_id: Optional[UUID] = None

    model_config = _camel


class PartyResponse(BaseModel):
    id: UUID
    party_type: str
    user_id: Optional[UUID] = None

    model_config = _camel


# --- Recurring rules ---

class MoneyRuleCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY")  # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str  # INCOME | EXPENSE
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category_id: Optional[UUID] = None
    frequency: str = Field(default="MONTHLY")  # DAILY | WEEKLY | BIWEEKLY | MONTHLY | QUARTERLY | HALF_YEARLY | YEARLY
    every_n: int = Field(default=1, ge=1, le=365)
    next_run_at: datetime
    end_at: Optional[datetime] = None
    max_runs: Optional[int] = Field(default=None, ge=1, le=10000)
    document_id: Optional[UUID] = None
    let_everyone_edit: bool = True
    parties: List[PartyInput] = Field(default_factory=list)

    model_config = _camel


class MoneyRuleUpdateRequest(BaseModel):
    """Omitted fields are unchanged; endAt / maxRuns / categoryId may be sent as null to clear."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    amount: Optional[float] = Field(default=None, gt=0)
    category_id: Optional[UUID] = None
    frequency: Optional[str] = None
    every_n: Optional[int] = Field(default=None, ge=1, le=365)
    next_run_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    max_runs: Optional[int] = Field(default=None, ge=1, le=10000)
    status: Optional[str] = None  # ACTIVE | PAUSED
    document_id: Optional[UUID] = None
    let_everyone_edit: Optional[bool] = None
    parties: Optional[List[PartyInput]] = None

    model_config = _camel


class MoneyRuleResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    kind: str
    name: str
    amount: float
    category_id: Optional[UUID] = None
    frequency: str
    every_n: int = 1
    next_run_at: datetime
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    end_at: Optional[datetime] = None
    max_runs: Optional[int] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: bool
    can_edit: bool = False
    created_by: UUID
    insurance_id: Optional[UUID] = None
    debt_id: Optional[UUID] = None
    status: str
    parties: List[PartyResponse]
    created_at: datetime
    updated_at: datetime

    model_config = _camel


class MoneyRuleListResponse(CamelPaginatedResponse[MoneyRuleResponse]):
    pass


# --- One-time events and recurring runs ---

class MoneyEventCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY")  # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str  # INCOME | EXPENSE
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    occurred_at: Optional[datetime] = None
    let_everyone_edit: bool = True
    parties: List[PartyInput] = Field(default_factory=list)

    model_config = _camel


class MoneyEventUpdateRequest(BaseModel):
    """Omitted fields are unchanged; categoryId may be sent as null to clear."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    amount: Optional[float] = Field(default=None, gt=0)
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    occurred_at: Optional[datetime] = None
    let_everyone_edit: Optional[bool] = None

    model_config = _camel


class MoneyEventResponse(BaseModel):
    id: UUID
    rule_id: Optional[UUID] = None
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    kind: str
    name: str
    amount: float
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: bool
    is_overdrawn: bool = False
    can_edit: bool = False
    occurred_at: datetime
    created_by: UUID
    parties: List[PartyResponse]
    created_at: datetime

    model_config = _camel


class MoneyEventListResponse(CamelPaginatedResponse[MoneyEventResponse]):
    pass
