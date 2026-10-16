"""In-process fake SSO for tests: RSA-signed tokens, JWKS and live /auth/me."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from karan_sso import SsoSettings

ISSUER = "https://auth.test/api/auth"
AUDIENCE = "karanparmar-apps"
APP_ID = "familyos"
KID = "test-key-1"
LEGACY_SECRET = "legacy-test-secret-0123456789abcdef0123"

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def sso_test_settings() -> SsoSettings:
    return SsoSettings(
        _env_file=None,
        SSO_BASE_URL="http://sso.test/api",
        SSO_ISSUER=ISSUER,
        SSO_AUDIENCE=AUDIENCE,
        SSO_JWT_SECRET=LEGACY_SECRET,
        SSO_APP_ID=APP_ID,
    )


def jwks_document() -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(SIGNING_KEY.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def make_token(
    user_id: str = "65f0c0ffee0000000000abcd",
    email: str = "user@test.com",
    *,
    role: str = "user",
    roles: dict[str, list[str]] | None = None,
    key: Any = SIGNING_KEY,
    alg: str = "RS256",
    **overrides: Any,
) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "name": email.split("@")[0],
        "email_verified": True,
        "role": role,
        "role_name": role,
        "roles": roles or {},
        "sid": "sess-1",
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    claims.update(overrides)
    headers = {"kid": KID} if alg == "RS256" else None
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


def make_legacy_token(user_id: str, email: str, **overrides: Any) -> str:
    """HS256 token signed with the rollout shared secret."""
    return make_token(user_id, email, key=LEGACY_SECRET, alg="HS256", **overrides)


class FakeSso:
    """Serves JWKS and /auth/me. /me mirrors the token unless overridden per user."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.me_status: int = 200
        self.me_error: Exception | None = None
        self.calls = {"jwks": 0, "me": 0}

    def set_user(self, user_id: str, *, role_name: str = "user", app_roles: dict[str, list[str]] | None = None) -> None:
        self.users[user_id] = {"role_name": role_name, "app_roles": app_roles or {}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/jwks.json"):
            self.calls["jwks"] += 1
            return httpx.Response(200, json=jwks_document())
        if path.endswith("/auth/me"):
            self.calls["me"] += 1
            if self.me_error is not None:
                raise self.me_error
            if self.me_status != 200:
                return httpx.Response(self.me_status, json={"detail": "fake"})
            auth = request.headers.get("authorization", "")
            claims = jwt.decode(auth.removeprefix("Bearer "), options={"verify_signature": False})
            uid = str(claims.get("user_id") or claims.get("sub"))
            me = {
                "id": uid,
                "email": claims.get("email"),
                "name": claims.get("name"),
                "email_verified": True,
                "role_name": claims.get("role") or "user",
                "app_roles": claims.get("roles") or {},
            }
            me.update(self.users.get(uid, {}))
            return httpx.Response(200, json=me)
        return httpx.Response(404, json={"detail": "not found"})

    def client_factory(self):
        transport = httpx.MockTransport(self.handler)
        return lambda: httpx.AsyncClient(transport=transport)
