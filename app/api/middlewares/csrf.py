"""
CSRF protection middleware (double-submit cookie pattern).

Validates that state-changing requests carry a matching, signed CSRF token in
both the ``x-csrf-token`` cookie and the ``X-CSRF-Token`` header.

Tokens are issued only by auth endpoints (login / refresh). This middleware
never generates tokens — on failure it revokes the refresh token and clears
all auth cookies so the client session is terminated.
"""

import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.auth_cookies import CSRF_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, clear_auth_cookies
from app.api.routes.auth.model import RefreshToken
from app.utils.security_and_auth import verify_csrf_token
from app.utils.security_and_auth import hash_token

logger = logging.getLogger(__name__)

_EXEMPT_PREFIXES = ("/api/auth/",)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


def _csrf_valid(request: Request) -> bool:
    header_token = request.headers.get("x-csrf-token")
    cookie_token = request.cookies.get(CSRF_TOKEN_COOKIE)
    if not header_token or not cookie_token or header_token != cookie_token:
        return False
    return verify_csrf_token(header_token)


async def _revoke_refresh_token(request: Request) -> None:
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        return

    hashed = hash_token(refresh_token)
    postgres_manager = request.app.state.postgres_session
    async for session in postgres_manager.get_session():
        stmt = select(RefreshToken).where(RefreshToken.token == hashed)
        result = await session.execute(stmt)
        stored = result.scalar_one_or_none()
        if stored is not None:
            await session.execute(delete(RefreshToken).where(RefreshToken.user_id == stored.user_id))
            await session.commit()
        break


async def _force_logout_response(request: Request) -> Response:
    await _revoke_refresh_token(request)
    response = JSONResponse(
        status_code=403,
        content={"detail": "CSRF token missing or invalid", "logged_out": True},
    )
    clear_auth_cookies(response)
    return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate CSRF tokens on state-changing requests outside auth routes."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_exempt(request.url.path) or request.method in _SAFE_METHODS:
            return await call_next(request)

        if not _csrf_valid(request):
            logger.warning("CSRF validation failed for %s %s", request.method, request.url.path)
            return await _force_logout_response(request)

        return await call_next(request)
