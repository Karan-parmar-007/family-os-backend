# app/api/middlewares/csrf.py
from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.cookies import CSRF_HEADER_NAME, CSRF_TOKEN_COOKIE

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_EXEMPT_PREFIXES = (
    "/health",
    "/api/familyos/health",
    "/api/familyos/auth/refresh",
    "/api/auth/refresh",
    "/api/familyos/auth/logout",
    "/api/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF. Family OS never sets this cookie — SSO does."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method.upper()
        path = request.url.path

        if method in SAFE_METHODS:
            return await call_next(request)

        if self._is_exempt_path(path, request):
            return await call_next(request)

        if not self._validate_csrf_token(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)

    def _is_exempt_path(self, path: str, request: Request) -> bool:
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return True
        referer = request.headers.get("referer", "")
        if "/docs" in referer or "/redoc" in referer:
            return True
        return False

    def _validate_csrf_token(self, request: Request) -> bool:
        cookie_token = request.cookies.get(CSRF_TOKEN_COOKIE)
        # Check both canonical header name and lowercase
        header_token = request.headers.get(CSRF_HEADER_NAME) or request.headers.get("x-csrf-token")
        if not cookie_token or not header_token:
            return False
        return secrets.compare_digest(cookie_token, header_token)
