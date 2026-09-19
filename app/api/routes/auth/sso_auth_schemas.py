# app/api/routes/auth/sso_auth_schemas.py
from __future__ import annotations

from uuid import UUID
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ProfileSummary(BaseModel):
    """Minimal profile data embedded in SessionResponse."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    display_name: str
    personal_currency: str
    timezone: str
    personal_code: str
    max_family_memberships: int


class SessionResponse(BaseModel):
    """GET /api/familyos/auth/session response — always 200."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    authenticated: bool
    is_owner: bool
    is_admin: bool
    email: str | None = None
    user_id: str | None = None
    role_name: str | None = None
    name: str | None = None
    profile: ProfileSummary | None = None


class TokenProxyResponse(BaseModel):
    """Response proxied from SSO refresh/logout."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    message: str
    access_token_expires_in: int | None = None


class MessageResponse(BaseModel):
    """Generic message envelope."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    message: str
    detail: Any = None
