"""Generalized entity owner dependency (extends income_owner pattern)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.db_dependencies import PGSessionDep
from app.api.routes.user.model import UserBase


async def require_entity_owner(
    current_user: LoggedInFamilyMemberDep,
    added_by_user_id: UUID,
) -> UserBase:
    if added_by_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the entity owner may perform this action",
        )
    return current_user


type EntityOwnerDep = Annotated[UserBase, Depends(require_entity_owner)]
