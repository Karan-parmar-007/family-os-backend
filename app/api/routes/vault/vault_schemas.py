from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class VaultPinSetupRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    pin: str = Field(..., min_length=4, max_length=32)

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VaultUnlockRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    pin: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VaultUnlockResponse(BaseModel):
    token: str
    expires_in_seconds: int

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VaultItemCreateRequest(BaseModel):
    scope: str = Field(default="FAMILY") # FAMILY | PERSONAL
    family_id: Optional[UUID] = None
    kind: str = Field(default="PASSWORD") # PASSWORD | FILE
    title: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    for_party_type: str = Field(default="FAMILY") # MEMBER | FAMILY | SELF
    for_user_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    is_protected: bool = True
    secret: Optional[str] = None # Plaintext to encrypt
    file_key: Optional[str] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VaultItemResponse(BaseModel):
    id: UUID
    scope: str
    family_id: Optional[UUID] = None
    owner_user_id: UUID
    kind: str
    title: str
    category: str
    for_party_type: str
    for_user_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    is_protected: bool
    secret: Optional[str] = None # populated only if unlocked
    file_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VaultItemListResponse(BaseModel):
    items: List[VaultItemResponse]
    pin_configured: bool
    is_unlocked: bool

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
