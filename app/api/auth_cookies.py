"""Shared auth cookie helpers for routes and CSRF middleware."""

from fastapi import Response

from app.config import auth_settings
from app.utils.security_and_auth import generate_csrf_token

API_PREFIX = "/api"
AUTH_COOKIE_PATH = f"{API_PREFIX}/auth"

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_TOKEN_COOKIE = "x-csrf-token"


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    *,
    csrf_token: str | None = None,
) -> str:
    """Set access, refresh, and CSRF cookies. Returns the CSRF token used."""
    csrf = csrf_token or generate_csrf_token()

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=API_PREFIX,
        max_age=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=AUTH_COOKIE_PATH,
        max_age=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    response.set_cookie(
        key=CSRF_TOKEN_COOKIE,
        value=csrf,
        httponly=False,
        secure=True,
        samesite=auth_settings.CSRF_COOKIE_SAMESITE,
        path=API_PREFIX,
    )
    return csrf


def clear_auth_cookies(response: Response) -> None:
    """Expire all auth-related cookies on the client."""
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path=API_PREFIX)
    response.delete_cookie(key=REFRESH_TOKEN_COOKIE, path=AUTH_COOKIE_PATH)
    response.delete_cookie(key=CSRF_TOKEN_COOKIE, path=API_PREFIX)
