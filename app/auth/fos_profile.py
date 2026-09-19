"""Resolve the Family OS profile for an authenticated SSO identity."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.db_dependencies import PGSessionDep
from app.api.routes.profile.model import FosProfile
from app.api.routes.profile.profile_service import ProfileService
from app.auth.dependencies import AuthenticatedDep


async def get_required_fos_profile(
    identity: AuthenticatedDep,
    session: PGSessionDep,
) -> FosProfile:
    """SSO JWT user_id is a Mongo ObjectId string, not fos_profiles.id."""
    profile = await ProfileService(session).get_by_sso_id(identity.user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Complete /me/setup first.",
        )
    if not profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profile is inactive",
        )
    return profile


FosProfileDep = Annotated[FosProfile, Depends(get_required_fos_profile)]
