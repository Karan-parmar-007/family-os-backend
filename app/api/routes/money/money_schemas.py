from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class PartyInput(BaseModel):
    party_type: str = Field(default="FAMILY") # MEMBER | FAMILY
    user_id: Optional[UUID] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PartyResponse(BaseModel):
    id: UUID
    party_type: str
    user_id: Optional[UUID] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --- Recurring Rules ---

class MoneyRuleCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str # INCOME | EXPENSE
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category_id: Optional[UUID] = None
    frequency: str = Field(default="MONTHLY") # DAILY, WEEKLY, MONTHLY, YEARLY
    next_run_at: datetime
    document_id: Optional[UUID] = None
    occurred_at: Optional[datetime] = None
    let_everyone_edit: bool = True
    parties: List[PartyInput] = Field(default_factory=list)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MoneyRuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    category_id: Optional[UUID] = None
    frequency: Optional[str] = None
    next_run_at: Optional[datetime] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: Optional[bool] = None
    parties: Optional[List[PartyInput]] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


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
    next_run_at: datetime
    document_id: Optional[UUID] = None
    let_everyone_edit: bool
    created_by: UUID
    insurance_id: Optional[UUID] = None
    debt_id: Optional[UUID] = None
    status: str
    parties: List[PartyResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MoneyRuleListResponse(BaseModel):
    items: List[MoneyRuleResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --- One-Time Events ---

class MoneyEventCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str # INCOME | EXPENSE
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    occurred_at: Optional[datetime] = None
    let_everyone_edit: bool = True
    parties: List[PartyInput] = Field(default_factory=list)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


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
    occurred_at: datetime
    created_by: UUID
    parties: List[PartyResponse]
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MoneyEventListResponse(BaseModel):
    items: List[MoneyEventResponse]
    total: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
