from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FamilyRelationshipCreateRequest(BaseModel):
    target_member_email: str = Field(..., min_length=3)
    relationship_type: str | None = None
    label: str | None = None


class FamilyRelationshipResponse(BaseModel):
    id: UUID
    family_a_id: UUID
    family_b_id: UUID
    relationship_type: str | None = None
    label: str | None = None
    status: str
    initiated_by_family_id: UUID
    initiated_by_user_id: UUID
    responded_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class FamilyRelationshipListResponse(BaseModel):
    items: list[FamilyRelationshipResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FamilyJoinCodeResponse(BaseModel):
    join_code: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class FamilyConnectByCodeRequest(BaseModel):
    join_code: str = Field(..., min_length=8, max_length=8, description="8-digit join code")
    label: str | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
