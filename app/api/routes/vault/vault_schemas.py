from datetime import datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel

from app.api.schemas.pagination import CamelPaginatedResponse

_camel = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class VaultPinSetupRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    pin: str = Field(..., min_length=4, max_length=32)

    model_config = _camel


class VaultUnlockRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    pin: str

    model_config = _camel


class VaultUnlockResponse(BaseModel):
    token: str
    expires_in_seconds: int

    model_config = _camel


class VaultItemCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str = Field(default="PASSWORD") # PASSWORD | FILE
    title: str = Field(..., min_length=1, max_length=255)
    category_id: Optional[UUID] = None
    for_party_type: str = Field(default="FAMILY") # MEMBER | FAMILY | SELF
    for_user_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    is_protected: bool = True
    let_everyone_edit: bool = False
    secret: Optional[str] = Field(default=None, max_length=10000) # Plaintext to encrypt
    file_key: Optional[str] = None

    model_config = _camel


class VaultItemUpdateRequest(BaseModel):
    """Omitted fields are unchanged; categoryId may be sent as null to clear."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category_id: Optional[UUID] = None
    for_party_type: Optional[str] = None
    for_user_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    is_protected: Optional[bool] = None
    let_everyone_edit: Optional[bool] = None
    secret: Optional[str] = Field(default=None, max_length=10000)

    model_config = _camel


class VaultItemResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: UUID
    kind: str
    title: str
    category: Optional[str] = None
    category_id: Optional[UUID] = None
    for_party_type: str
    for_user_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    is_protected: bool
    let_everyone_edit: bool = False
    can_edit: bool = False
    secret: Optional[str] = None # populated only if unlocked
    file_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = _camel


class VaultItemListResponse(CamelPaginatedResponse[VaultItemResponse]):
    pin_configured: bool
    is_unlocked: bool
    password_count: int = 0
    document_count: int = 0
