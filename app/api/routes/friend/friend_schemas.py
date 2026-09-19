from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FriendRequestByCode(BaseModel):
    friend_code: str = Field(..., min_length=8, max_length=8)


class FriendCodeResponse(BaseModel):
    friend_code: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FriendshipResponse(BaseModel):
    id: UUID
    user_a_id: UUID
    user_b_id: UUID
    requested_by: UUID
    status: str
    created_at: datetime
    # Convenience fields for the current viewer
    other_user_id: UUID | None = None
    other_user_name: str | None = None
    direction: str | None = None  # INCOMING | OUTGOING | ACTIVE

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class FriendshipListResponse(BaseModel):
    items: list[FriendshipResponse]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FriendUserOption(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class FriendUserListResponse(BaseModel):
    items: list[FriendUserOption]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
