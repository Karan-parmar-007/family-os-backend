"""Dependency chain: login required → family membership verified."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.db_dependencies import PGSessionDep
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserFamilyLink
from app.auth.fos_profile import FosProfileDep


async def get_logged_in_family_member(
    profile: FosProfileDep,
    family_id: UUID,
    session: PGSessionDep,
) -> FosProfile:
    stmt = select(UserFamilyLink).where(
        UserFamilyLink.user_id == profile.id,
        UserFamilyLink.family_id == family_id,
    )
    result = await session.execute(stmt)
    link = result.scalar_one_or_none()

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this family",
        )

    return profile


async def get_logged_in_family_manager(
    profile: FosProfileDep,
    family_id: UUID,
    session: PGSessionDep,
) -> FosProfile:
    stmt = select(UserFamilyLink).where(
        UserFamilyLink.user_id == profile.id,
        UserFamilyLink.family_id == family_id,
    )
    result = await session.execute(stmt)
    link = result.scalar_one_or_none()

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this family",
        )

    if not link.is_family_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a manager of this family",
        )

    return profile


type LoggedInFamilyMemberDep = Annotated[FosProfile, Depends(get_logged_in_family_member)]
type LoggedInFamilyManagerDep = Annotated[FosProfile, Depends(get_logged_in_family_manager)]

# Backward-compatible alias
type FamilyMemberDep = LoggedInFamilyMemberDep
