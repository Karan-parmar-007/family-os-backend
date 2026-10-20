"""Family OS ↔ SSO integration via the shared karan_sso SDK.

Runs without Postgres/Mongo: the PG session dependency is replaced with a stub
that returns empty results, and the SDK talks to tests/sso_fakes.FakeSso
(JWKS + live /auth/me) through httpx.MockTransport.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.db_dependencies import _get_pg_session
from main import app
from tests.sso_fakes import APP_ID, OTHER_KEY, make_legacy_token, make_token

SESSION = "/api/familyos/auth/session"
PROTECTED = "/api/familyos/currency-rates"
ADMIN = "/api/familyos/admin/currencies"
USER_ID = "65f0c0ffee0000000000abcd"


class _EmptyResult:
    def scalars(self) -> "_EmptyResult":
        return self

    def all(self) -> list[Any]:
        return []

    def scalar_one_or_none(self) -> None:
        return None

    def scalar_one(self) -> int:
        return 0

    def scalar(self) -> int:
        return 0


class _StubSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> _EmptyResult:
        return _EmptyResult()


@pytest.fixture
def client():
    async def _stub_pg_session():
        yield _StubSession()

    app.dependency_overrides[_get_pg_session] = _stub_pg_session
    try:
        # No `with`: skip lifespan (DB connects / scheduler) — auth only.
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(_get_pg_session, None)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── GET /auth/session (local verification only, always 200) ──────────────


def test_session_anonymous(client, fake_sso):
    res = client.get(SESSION)
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is False
    assert data["email"] is None
    assert data["isAdmin"] is False
    assert data["isOwner"] is False


def test_session_authenticated_cookie(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "karan@karanparmar.in"))
    res = client.get(SESSION)
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["email"] == "karan@karanparmar.in"
    assert data["userId"] == USER_ID
    assert data["roleName"] == "user"
    assert data["isAdmin"] is False
    assert data["profile"] is None
    # Local verification only: never calls SSO /auth/me.
    assert fake_sso.calls["me"] == 0


def test_session_reports_app_admin_from_token(client, fake_sso):
    token = make_token(USER_ID, "a@test.com", roles={APP_ID: ["admin"]})
    res = client.get(SESSION, headers=_bearer(token))
    data = res.json()
    assert data["isAdmin"] is True
    assert data["isOwner"] is False
    assert data["appRoles"] == {APP_ID: ["admin"]}


def test_session_owner_flags(client, fake_sso):
    res = client.get(SESSION, headers=_bearer(make_token(USER_ID, "o@test.com", role="owner")))
    data = res.json()
    assert data["isOwner"] is True
    assert data["isAdmin"] is True


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        make_token(USER_ID, "x@test.com", key=OTHER_KEY),  # wrong signing key
        make_token(USER_ID, "x@test.com", exp=datetime.now(timezone.utc) - timedelta(minutes=5)),
        make_token(USER_ID, "x@test.com", type="refresh"),
        make_token(USER_ID, "x@test.com", iss="https://evil.test/api/auth"),
        make_token(USER_ID, "x@test.com", aud="some-oauth-client"),
    ],
    ids=["garbage", "wrong-key", "expired", "refresh-type", "wrong-issuer", "wrong-audience"],
)
def test_session_invalid_token_is_anonymous_200(client, fake_sso, token):
    client.cookies.set("access_token", token)
    res = client.get(SESSION)
    assert res.status_code == 200
    assert res.json()["authenticated"] is False


def test_session_accepts_legacy_hs256_during_rollout(client, fake_sso):
    client.cookies.set("access_token", make_legacy_token(USER_ID, "legacy@test.com"))
    data = client.get(SESSION).json()
    assert data["authenticated"] is True
    assert data["email"] == "legacy@test.com"


# ── Protected route (IdentityDep) ────────────────────────────────────────


def test_protected_route_requires_token(client, fake_sso):
    assert client.get(PROTECTED).status_code == 401


def test_protected_route_with_token(client, fake_sso):
    res = client.get(PROTECTED, headers=_bearer(make_token(USER_ID, "u@test.com")))
    assert res.status_code == 200
    assert res.json() == {"items": []}
    assert fake_sso.calls["me"] == 0


def test_protected_route_with_cookie(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "u@test.com"))
    assert client.get(PROTECTED).status_code == 200


def test_protected_route_rejects_bad_token(client, fake_sso):
    res = client.get(PROTECTED, headers=_bearer(make_token(USER_ID, "u@test.com", key=OTHER_KEY)))
    assert res.status_code == 401


# ── Admin route (AdminDep, live /auth/me) ────────────────────────────────


def test_admin_route_requires_token(client, fake_sso):
    assert client.get(ADMIN).status_code == 401


def test_admin_route_forbidden_for_non_admin(client, fake_sso):
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "u@test.com")))
    assert res.status_code == 403
    assert fake_sso.calls["me"] == 1


@pytest.mark.parametrize(
    ("role_name", "app_roles"),
    [("owner", {}), ("super_admin", {}), ("user", {APP_ID: ["admin"]})],
    ids=["owner", "super_admin", "familyos-app-admin"],
)
def test_admin_route_allows_admins(client, fake_sso, role_name, app_roles):
    fake_sso.set_user(USER_ID, role_name=role_name, app_roles=app_roles)
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "a@test.com")))
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0, "page": 1, "pageSize": 10, "totalPages": 0}


def test_admin_route_ignores_other_apps_admin_role(client, fake_sso):
    fake_sso.set_user(USER_ID, role_name="user", app_roles={"portfolio": ["admin"]})
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "a@test.com")))
    assert res.status_code == 403


def test_admin_route_uses_live_role_not_token(client, fake_sso):
    # Token still says super_admin, but the user was demoted in SSO.
    fake_sso.set_user(USER_ID, role_name="user")
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "a@test.com", role="super_admin")))
    assert res.status_code == 403


def test_admin_route_revoked_session_is_401(client, fake_sso):
    fake_sso.me_status = 401
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "a@test.com", role="owner")))
    assert res.status_code == 401


@pytest.mark.parametrize("failure", ["http-500", "unreachable"])
def test_admin_route_sso_outage_is_503(client, fake_sso, failure):
    if failure == "http-500":
        fake_sso.me_status = 500
    else:
        fake_sso.me_error = httpx.ConnectError("connection refused")
    res = client.get(ADMIN, headers=_bearer(make_token(USER_ID, "a@test.com", role="owner")))
    assert res.status_code == 503


def test_currency_rate_mutations_require_admin(client, fake_sso):
    body = {"baseCurrency": "USD", "quoteCurrency": "INR", "rate": "83.1", "effectiveFrom": "2026-01-01T00:00:00Z"}
    res = client.post(PROTECTED, json=body, headers=_bearer(make_token(USER_ID, "u@test.com")))
    assert res.status_code == 403


# ── CSRF (karan_sso CSRFMiddleware) ──────────────────────────────────────


def test_csrf_cookie_mutation_without_header_is_403(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "u@test.com"))
    client.cookies.set("csrf_token", "csrf-abc")
    res = client.post("/api/familyos/me/setup", json={"displayName": "Karan"})
    assert res.status_code == 403
    assert res.json()["detail"] == "CSRF token missing or invalid"


def test_csrf_mismatched_header_is_403(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "u@test.com"))
    client.cookies.set("csrf_token", "csrf-abc")
    res = client.post("/api/familyos/me/setup", json={}, headers={"X-CSRF-Token": "other"})
    assert res.status_code == 403


def test_csrf_no_docs_referer_bypass(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "u@test.com"))
    client.cookies.set("csrf_token", "csrf-abc")
    res = client.post(
        "/api/familyos/me/setup",
        json={"displayName": "Karan"},
        headers={"Referer": "https://familyos.karanparmar.in/docs"},
    )
    assert res.status_code == 403


def test_csrf_matching_header_passes_through(client, fake_sso):
    client.cookies.set("access_token", make_token(USER_ID, "u@test.com"))
    client.cookies.set("csrf_token", "csrf-abc")
    # Past CSRF: request body validation now answers (422), not the CSRF guard.
    res = client.post("/api/familyos/me/setup", json={}, headers={"X-CSRF-Token": "csrf-abc"})
    assert res.status_code == 422


def test_csrf_not_required_for_bearer_only(client, fake_sso):
    res = client.post("/api/familyos/me/setup", json={}, headers=_bearer(make_token(USER_ID, "u@test.com")))
    assert res.status_code == 422


# ── Removed app-side auth proxies ────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/familyos/auth/refresh",
        "/api/familyos/auth/logout",
        "/api/auth/refresh",
        "/api/auth/logout",
        "/api/auth/session",
        "/api/auth/login",
        "/api/auth/signup",
    ],
)
def test_auth_proxies_removed(client, fake_sso, path):
    res = client.post(path, json={})
    assert res.status_code in (404, 405)
