# app/api/middlewares/csrf.py
"""
CSRF protection middleware.

Protects all non-safe HTTP methods (POST, PUT, DELETE, PATCH) on non-auth
routes by requiring a valid CSRF token in the ``X-CSRF-Token`` request header.
The token is issued as a non-HttpOnly ``x-csrf-token`` cookie on every response
so the React SPA can read it and send it in the header.

Auth routes (/auth/*) are exempt — they serve the frontend that obtains the
token via the middleware on subsequent protected requests.
"""

import logging
import secrets

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Routes exempt from CSRF checks.
_EXEMPT_PREFIXES = ("/auth/",)
# HTTP methods that don't modify state — always exempt.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_exempt(path: str) -> bool:
    """Return ``True`` if *path* should skip CSRF validation."""
    if path.startswith(_EXEMPT_PREFIX_PREFIXES):
        return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """Issue an ``x-csrf-token`` cookie and validate it on state-changing requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        from app.config import auth_settings

        # --- exempt paths / safe methods --------------------------------
        if _is_exempt(request.url.path) or request.method in _SAFE_METHODS:
            response = await call_next(request)
            return response

        # --- validate token ---------------------------------------------
        secret = self._get_csrf_secret()
        token = request.headers.get("x-csrf-token")

        if not token or not self._verify(secret, token):
            logger.warning("CSRF validation failed for %s %s", request.method, request.url.path)
            return Response(
                content='{"detail":"CSRF token missing or invalid"}',
                status_code=403,
                media_type="application/json",
            )

        # --- proceed ----------------------------------------------------
        response = await call_next(request)

        # Issue a fresh token cookie only if the request didn't already
        # carry one — avoids rotating the token on every protected call.
        existing = request.cookies.get("x-csrf-token")
        if existing:
            # Validate the existing token; if valid, keep it.
            if self._verify(secret, existing):
                response.set_cookie(
                    key="x-csrf-token",
                    value=existing,
                    httponly=False,
                    samesite=auth_settings.CSRF_COOKIE_SAMESITE,
                    secure=True,
                    path="/",
                )
                return response
            # Token expired — fall through to issue a new one.

        new_token = secrets.token_urlsafe(32)
        response.set_cookie(
            key="x-csrf-token",
            value=new_token,
            httponly=False,
            samesite=auth_settings.CSRF_COOKIE_SAMESITE,
            secure=True,
            path="/",
        )
        return response

    # -- internals --------------------------------------------------------

    @staticmethod
    def _get_csrf_secret() -> str:
        # Deferred import to avoid circular imports at module load time.
        from app.config import auth_settings  # noqa: local import

        return auth_settings._csrf_secret


    @staticmethod
    def _verify(secret: str, token: str) -> bool:
        """Verify a CSRF token using HMAC-SHA256 via ``itsdangerous``."""
        from itsdangerous import Signer

        signer = Signer(secret, salt="csrf")
        try:
            signer.unsign(token)
            return True
        except Exception:
            return False
