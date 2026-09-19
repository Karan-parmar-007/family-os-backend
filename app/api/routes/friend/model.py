from datetime import datetime
from typing import ClassVar
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel, func


class Friendship(SQLModel, table=True):
    __tablename__: ClassVar[str] = "friendships"
    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_friendships_user_pair"),
    )

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    user_a_id: UUID = Field(foreign_key="users.id", index=True)
    user_b_id: UUID = Field(foreign_key="users.id", index=True)
    requested_by: UUID = Field(foreign_key="users.id")
    status: str = Field(default="PENDING", index=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


def canonical_user_pair(user_id_1: UUID, user_id_2: UUID) -> tuple[UUID, UUID]:
    """Order UUIDs so (a,b) and (b,a) map to the same unique pair."""
    if str(user_id_1) <= str(user_id_2):
        return user_id_1, user_id_2
    return user_id_2, user_id_1
