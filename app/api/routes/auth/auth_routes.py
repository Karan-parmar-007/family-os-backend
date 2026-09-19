# app/api/routes/auth/auth_routes.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth.cookies import CSRF_HEADER_NAME, CSRF_TOKEN_COOKIE
from app.auth.dependencies import SessionIdentityDep
from app.auth.sso_client import cookie_header_from_request, proxy_sso
from app.api.routes.auth.sso_auth_schemas import (
    ProfileSummary,
    SessionResponse,
    TokenProxyResponse,
)
from app.api.db_dependencies import PGSessionDep
from app.api.routes.profile.profile_service import ProfileService
from app.config import auth_settings
from app.core.errors import UnauthorizedError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _forward_set_cookies(upstream: object, response: Response) -> None:
    """Copy Set-Cookie headers from an httpx response onto the FastAPI response."""
    headers = getattr(upstream, "headers", None)
    if headers is None:
        return
    get_list = getattr(headers, "get_list", None)
    if callable(get_list):
        values = get_list("set-cookie")
    else:
        raw = headers.get("set-cookie")
        values = [raw] if raw else []
    for value in values:
        if value:
            response.headers.append("set-cookie", value)


@router.get("/session", response_model=SessionResponse, summary="Get current session identity from SSO")
async def get_session(
    identity: SessionIdentityDep,
    session: PGSessionDep,
) -> SessionResponse:
    """Always 200 — anonymous loads must not trip auth refresh loops."""
    if identity is None:
        return SessionResponse(
            authenticated=False,
            is_owner=False,
            is_admin=False,
            email=None,
            user_id=None,
            role_name=None,
            name=None,
            profile=None,
        )
    role = (identity.role_name or "").strip().lower()
    is_admin = role in {"owner", "super_admin"}

    # Load FosProfile if SSO is authenticated
    profile_summary: ProfileSummary | None = None
    try:
        svc = ProfileService(session)
        fos_profile = await svc.get_by_sso_id(identity.user_id)
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
        is_admin=is_admin,
        email=identity.email,
        user_id=identity.user_id,
        role_name=identity.role_name,
        name=identity.name,
        profile=profile_summary,
    )


@router.post("/refresh", response_model=TokenProxyResponse, summary="Proxy SSO refresh")
async def refresh_session(request: Request) -> Response:
    """Proxy SSO refresh. Browser hits this path so Path=/api/auth cookies apply."""
    cookie_header = request.headers.get("cookie") or cookie_header_from_request(
        dict(request.cookies)
    )
    csrf = request.headers.get(CSRF_HEADER_NAME) or request.cookies.get(CSRF_TOKEN_COOKIE)
    try:
        upstream = await proxy_sso("POST", "/auth/refresh", cookie_header=cookie_header, csrf_token=csrf)
    except UnauthorizedError as exc:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    try:
        body = upstream.json()
    except ValueError:
        body = {"message": upstream.text or "Token refresh failed"}

    if upstream.status_code >= 400:
        response = JSONResponse(
            status_code=upstream.status_code,
            content={"detail": body.get("detail") or body.get("message") or "Refresh failed"},
        )
        _forward_set_cookies(upstream, response)
        return response

    response = JSONResponse(
        status_code=200,
        content={
            "access_token_expires_in": body.get("access_token_expires_in"),
            "message": body.get("message") or "Token refreshed successfully",
        },
    )
    _forward_set_cookies(upstream, response)
    return response


@router.post("/logout", response_model=TokenProxyResponse, summary="Proxy SSO logout")
async def logout_session(request: Request) -> Response:
    """Proxy SSO logout and forward Set-Cookie clears."""
    cookie_header = request.headers.get("cookie") or cookie_header_from_request(
        dict(request.cookies)
    )
    csrf = request.headers.get(CSRF_HEADER_NAME) or request.cookies.get(CSRF_TOKEN_COOKIE)
    try:
        upstream = await proxy_sso("POST", "/auth/logout", cookie_header=cookie_header, csrf_token=csrf)
    except UnauthorizedError as exc:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    try:
        body = upstream.json()
    except ValueError:
        body = {"message": upstream.text or "Logged out"}

    status_code = 200 if upstream.status_code < 500 else upstream.status_code
    response = JSONResponse(
        status_code=status_code,
        content={
            "message": body.get("message") or body.get("detail") or "Logged out successfully",
            "access_token_expires_in": None,
        },
    )
    _forward_set_cookies(upstream, response)
    if not any(k.lower() == "set-cookie" for k in response.headers.keys()):
        is_prod = auth_settings.ENVIRONMENT == "production"
        response.delete_cookie(key=auth_settings.ACCESS_TOKEN_COOKIE_NAME, path="/", secure=is_prod, httponly=True, samesite="lax")
        response.delete_cookie(key=auth_settings.CSRF_COOKIE_NAME, path="/", secure=is_prod, httponly=False, samesite="lax")
        response.delete_cookie(key="refresh_token", path="/api/auth", secure=is_prod, httponly=True, samesite="lax")
    return response
