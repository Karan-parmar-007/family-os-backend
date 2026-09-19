# app/auth/jwt.py
from __future__ import annotations

from typing import Any

import jwt

from app.config import auth_settings
from app.core.errors import UnauthorizedError


def decode_sso_access_token(token: str) -> dict[str, Any]:
    """Decode an SSO access token. Raises UnauthorizedError on any problem.

    Do not pass audience= or issuer= — SSO tokens carry neither claim.
    """
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    if not secret:
        raise UnauthorizedError("Authentication secret not configured")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[auth_settings.SSO_JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired session") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")
    if not payload.get("email"):
        raise UnauthorizedError("Token missing email claim")
    return payload
