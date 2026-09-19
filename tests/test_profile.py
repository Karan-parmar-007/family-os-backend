from unittest.mock import patch
import jwt
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.config import auth_settings
from main import app


def _create_token(user_id: str, email: str) -> str:
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=auth_settings.SSO_JWT_ALGORITHM)


def test_get_me_unauthenticated():
    with TestClient(app) as client:
        res = client.get("/api/familyos/me")
        assert res.status_code == 401


def test_get_me_no_profile():
    suffix = uuid4().hex[:8]
    token = _create_token(f"sso_new_user_{suffix}", f"newuser{suffix}@test.com")
    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        res = client.get("/api/familyos/me")
        assert res.status_code == 404
        assert "Profile not found" in res.json()["detail"]


def test_profile_setup_flow():
    suffix = uuid4().hex[:8]
    user_id = f"sso_setup_flow_{suffix}"
    email = f"setup_{suffix}@test.com"
    token = _create_token(user_id, email)
    csrf = "csrf-token-12345"

    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        client.cookies.set("csrf_token", csrf)
        headers = {"X-CSRF-Token": csrf}

        # 1. Validation test: all field errors caught without early escape
        bad_req = {
            "displayName": "",
            "currencyCode": "XYZ",
            "timezone": "Invalid/TZ",
            "personalSavingsOrigin": "-100",
        }
        res = client.post("/api/familyos/me/setup", json=bad_req, headers=headers)
        assert res.status_code == 422
        raw_detail = res.json()["detail"]
        if isinstance(raw_detail, list):
            err_fields = [e["loc"][-1] for e in raw_detail]
        else:
            err_fields = list(raw_detail.keys())
        assert "displayName" in err_fields
        assert "timezone" in err_fields
        assert "personalSavingsOrigin" in err_fields

        # 2. Valid setup
        good_req = {
            "displayName": "Karan Tester",
            "currencyCode": "USD",
            "timezone": "Asia/Kolkata",
            "personalSavingsOrigin": "1500.50",
        }
        res = client.post("/api/familyos/me/setup", json=good_req, headers=headers)
        assert res.status_code == 201
        profile = res.json()
        assert profile["displayName"] == "Karan Tester"
        assert profile["personalCurrency"] == "USD"
        assert profile["timezone"] == "Asia/Kolkata"
        assert len(profile["personalCode"]) == 8
        assert profile["maxFamilyMemberships"] == 2
        assert profile["isActive"] is True

        # 3. Repeat setup is rejected (409 Conflict)
        res_dup = client.post("/api/familyos/me/setup", json=good_req, headers=headers)
        assert res_dup.status_code == 409

        # 4. GET /api/me returns the profile
        res_me = client.get("/api/familyos/me")
        assert res_me.status_code == 200
        assert res_me.json()["id"] == profile["id"]

        # 5. GET /api/familyos/auth/session returns profile summary
        with patch("app.auth.dependencies.fetch_sso_me", return_value={"role_name": "member", "name": "Karan Tester"}):
            res_session = client.get("/api/familyos/auth/session")
        assert res_session.status_code == 200
        sess_data = res_session.json()
        assert sess_data["authenticated"] is True
        assert sess_data["profile"] is not None
        assert sess_data["profile"]["displayName"] == "Karan Tester"
        assert sess_data["profile"]["personalCode"] == profile["personalCode"]

        # 6. PATCH /api/me updates profile fields
        update_req = {
            "displayName": "Karan Updated",
            "currencyCode": "EUR",
        }
        res_patch = client.patch("/api/familyos/me", json=update_req, headers=headers)
        assert res_patch.status_code == 200
        assert res_patch.json()["displayName"] == "Karan Updated"
        assert res_patch.json()["personalCurrency"] == "EUR"
