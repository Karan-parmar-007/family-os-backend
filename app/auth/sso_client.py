# app/auth/sso_client.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import auth_settings
from app.core.errors import UnauthorizedError

logger = logging.getLogger(__name__)

OWNER_ROLE_NAMES = frozenset({"owner"})

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _sso_url(path: str) -> str:
    base = auth_settings.SSO_BASE_URL.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def cookie_header_from_request(cookies: dict[str, str]) -> str:
    """Build a Cookie header from a cookie mapping."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


async def fetch_sso_me(*, cookie_header: str) -> dict[str, Any] | None:
    """Return live SSO user info (includes role_name) or None if unauthenticated."""
    if not cookie_header.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _sso_url("/auth/me"),
                headers={"Cookie": cookie_header},
            )
    except httpx.HTTPError as exc:
        logger.warning("SSO /auth/me unreachable: %s", exc)
        return None

    if response.status_code == 401:
        return None
    if response.status_code >= 400:
        logger.warning(
            "SSO /auth/me returned %s: %s",
            response.status_code,
            response.text[:200],
        )
        return None
    try:
        data = response.json()
    except ValueError:
        logger.warning("SSO /auth/me returned non-JSON")
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_owner_role(role_name: str | None) -> bool:
    if not role_name:
        return False
    return role_name.strip().lower() in OWNER_ROLE_NAMES


async def proxy_sso(
    method: str,
    path: str,
    *,
    cookie_header: str,
    csrf_token: str | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Forward an auth call to SSO, preserving Cookie / CSRF."""
    headers: dict[str, str] = {}
    if cookie_header:
        headers["Cookie"] = cookie_header
    if csrf_token:
        headers[auth_settings.CSRF_HEADER_NAME] = csrf_token
    kwargs: dict[str, Any] = {
        "method": method.upper(),
        "url": _sso_url(path),
        "headers": headers,
    }
    # Avoid sending a JSON body on GET/HEAD — some servers reject it.
    if method.upper() not in {"GET", "HEAD"}:
        kwargs["json"] = json_body if json_body is not None else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await client.request(**kwargs)
    except httpx.HTTPError as exc:
        logger.warning("SSO proxy %s %s failed: %s", method, path, exc)
        raise UnauthorizedError("SSO unavailable") from exc
