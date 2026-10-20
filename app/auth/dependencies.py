# app/auth/dependencies.py
"""Family OS auth dependencies — thin adapters over the shared `karan_sso` SDK.

- `OptionalIdentityDep` / `AuthenticatedDep`: local JWT verification (JWKS), no SSO call.
- `AdminDep` / `OwnerDep` / `require_role(...)`: live check via SSO `/auth/me`
  (demotions and revoked sessions apply immediately; SSO outage → 503, not 403).
  Admin = global owner/super_admin, or app role `admin` in SSO_APP_ID (familyos).

SSO user ids (`identity.user_id`) are Mongo ObjectId strings, not UUIDs. Routes that
need a Family OS user id must use `FosProfileDep` / `LoggedInUserDep` (fos_profiles.id).
"""
from __future__ import annotations

from karan_sso import SsoIdentity
from karan_sso.fastapi import (
    AdminDep,
    IdentityDep,
    OptionalIdentityDep,
    OwnerDep,
    get_sso,
    require_role,
)

AuthenticatedDep = IdentityDep


def is_app_admin(identity: SsoIdentity) -> bool:
    """Same rule as `AdminDep`, evaluated on the given identity (no live call)."""
    return get_sso().is_app_admin(identity)


__all__ = [
    "AdminDep",
    "AuthenticatedDep",
    "IdentityDep",
    "OptionalIdentityDep",
    "OwnerDep",
    "SsoIdentity",
    "is_app_admin",
    "require_role",
]
