# app/api/routes/auth/auth_routes.py
"""Family OS session info.

Sign-in, refresh and logout are handled by SSO directly (browser → /api/auth/*).
This router only exposes the Family OS view of the current session.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.db_dependencies import PGSessionDep
from app.api.routes.auth.sso_auth_schemas import ProfileSummary, SessionResponse
from app.api.routes.profile.profile_service import ProfileService
from app.auth.dependencies import OptionalIdentityDep, is_app_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session", response_model=SessionResponse, summary="Current SSO identity + Family OS profile")
async def get_session(
    identity: OptionalIdentityDep,
    session: PGSessionDep,
) -> SessionResponse:
    """200 for signed-in and anonymous callers alike (never 401, never refreshes).

    Identity comes from local token verification only; role flags are UI hints
    (privileged routes re-check live via AdminDep / OwnerDep).
    """
    if identity is None:
        return SessionResponse(authenticated=False, is_owner=False, is_admin=False)

    profile_summary: ProfileSummary | None = None
    try:
        fos_profile = await ProfileService(session).get_by_sso_id(identity.user_id)
        if fos_profile is not None:
            profile_summary = ProfileSummary(
                id=fos_profile.id,
                display_name=fos_profile.display_name,
                personal_currency=fos_profile.personal_currency,
                timezone=fos_profile.timezone,
                personal_code=fos_profile.personal_code,
                max_family_memberships=fos_profile.max_family_memberships,
            )
    except Exception:
        logger.exception("Failed to load FosProfile for session")

    return SessionResponse(
        authenticated=True,
        is_owner=identity.is_owner,
        is_admin=is_app_admin(identity),
        email=identity.email,
        user_id=identity.user_id,
        role_name=identity.role,
        app_roles=identity.roles,
        name=identity.name,
        profile=profile_summary,
    )
