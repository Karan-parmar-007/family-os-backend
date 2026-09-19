import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import decode_sso_access_token
from app.config import auth_settings
from app.core.errors import UnauthorizedError
from main import app


def test_decode_sso_access_token_success():
    payload = {
        "sub": "user_12345",
        "user_id": "user_12345",
        "email": "karan@example.com",
        "type": "access",
    }
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    token = jwt.encode(payload, secret, algorithm=auth_settings.SSO_JWT_ALGORITHM)

    decoded = decode_sso_access_token(token)
    assert decoded["email"] == "karan@example.com"
    assert decoded["user_id"] == "user_12345"


def test_decode_sso_access_token_invalid():
    with pytest.raises(UnauthorizedError):
        decode_sso_access_token("invalid.token.here")

    # Wrong secret
    payload = {"sub": "1", "email": "test@test.com", "type": "access"}
    bad_token = jwt.encode(payload, "wrong_secret", algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_sso_access_token(bad_token)

    # Wrong token type
    refresh_payload = {"sub": "1", "email": "test@test.com", "type": "refresh"}
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    refresh_token = jwt.encode(refresh_payload, secret, algorithm="HS256")
    with pytest.raises(UnauthorizedError, match="Invalid token type"):
        decode_sso_access_token(refresh_token)


def test_session_endpoint_anonymous():
    with TestClient(app) as client:
        res = client.get("/api/familyos/auth/session")
        assert res.status_code == 200
        data = res.json()
        assert data["authenticated"] is False
        assert data["email"] is None
        assert data["isAdmin"] is False


def test_session_endpoint_authenticated():
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    payload = {
        "sub": "sso_abc123",
        "user_id": "sso_abc123",
        "email": "karan@karanparmar.in",
        "type": "access",
    }
    token = jwt.encode(payload, secret, algorithm=auth_settings.SSO_JWT_ALGORITHM)

    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        res = client.get("/api/familyos/auth/session")
        assert res.status_code == 200
        data = res.json()
        assert data["authenticated"] is True
        assert data["email"] == "karan@karanparmar.in"
        assert data["userId"] == "sso_abc123"


def test_csrf_middleware_enforced():
    with TestClient(app) as client:
        res = client.post("/api/familyos/me/setup", json={"displayName": "Karan"})
        assert res.status_code == 403
        assert res.json()["detail"] == "CSRF token missing or invalid"


def test_legacy_auth_disabled():
    with TestClient(app) as client:
        csrf = "valid-csrf-token"
        client.cookies.set("csrf_token", csrf)
        headers = {"X-CSRF-Token": csrf}
        res = client.post("/api/auth/login", json={"email": "a@b.com", "password": "StrongPass123!"}, headers=headers)
        assert res.status_code == 404

        res = client.post("/api/auth/signup", json={"email": "a@b.com", "password": "StrongPass123!", "name": "A"}, headers=headers)
        assert res.status_code == 404
