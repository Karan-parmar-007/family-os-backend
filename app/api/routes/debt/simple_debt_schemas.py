from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class DebtCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    owner_type: str = Field(default="FAMILY") # MEMBER | FAMILY | SELF
    owner_user_id: Optional[UUID] = None
    name: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)
    amount_paid: float = Field(default=0.0, ge=0)
    has_emi: bool = False
    emi_amount: Optional[float] = Field(default=None, gt=0)
    frequency: Optional[str] = Field(default="MONTHLY")
    next_emi_date: Optional[datetime] = None
    add_emi_to_paid: bool = True
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: bool = True

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DebtUpdateRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    amount_paid: Optional[float] = Field(default=None, ge=0)
    add_emi_to_paid: Optional[bool] = None
    category_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: Optional[bool] = None
    status: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DebtResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_type: str
    owner_user_id: Optional[UUID] = None
    name: str
    amount: float
    amount_paid: float
    remaining_amount: float
    has_emi: bool
    add_emi_to_paid: bool
    category_id: Optional[UUID] = None
    linked_rule_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    let_everyone_edit: bool
    created_by: UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DebtListResponse(BaseModel):
    items: List[DebtResponse]
    total: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
