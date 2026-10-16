import pytest
from decimal import Decimal
from uuid import uuid4
from fastapi.testclient import TestClient

from tests.sso_fakes import make_token
from main import app


def _create_token(user_id: str, email: str) -> str:
    return make_token(user_id, email)


def test_admin_gate_unauthorized(fake_sso):
    with TestClient(app) as client:
        # 1. Anonymous
        res = client.get("/api/familyos/admin/currencies")
        assert res.status_code == 401

        # 2. Authenticated but non-admin role
        token = _create_token("regular_user_1", "user1@test.com")
        client.cookies.set("access_token", token)
        # Live SSO /auth/me says plain member
        fake_sso.set_user("regular_user_1", role_name="member")
        res = client.get("/api/familyos/admin/currencies")
        assert res.status_code == 403


def test_admin_currencies_crud(fake_sso):
    admin_id = f"admin_{uuid4().hex[:6]}"
    token = _create_token(admin_id, "admin@test.com")
    csrf = "admin-csrf-123"

    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        client.cookies.set("csrf_token", csrf)
        headers = {"X-CSRF-Token": csrf}

        fake_sso.set_user(admin_id, role_name="owner")

        # 1. List currencies
        res = client.get("/api/familyos/admin/currencies")
        assert res.status_code == 200
        data = res.json()["items"]
        codes = [c["code"] for c in data]
        assert "USD" in codes
        assert "INR" in codes

        # 2. Validation: bad currency request
        bad_req = {"code": "TOOLONG", "name": "", "symbol": "X", "rateToUsd": -5}
        res_bad = client.post("/api/familyos/admin/currencies", json=bad_req, headers=headers)
        assert res_bad.status_code == 422

        # 3. Create new currency (CHF)
        new_curr = {
            "code": "CHF",
            "name": "Swiss Franc",
            "symbol": "CHF",
            "rateToUsd": "1.12",
            "isActive": True,
        }
        res_create = client.post("/api/familyos/admin/currencies", json=new_curr, headers=headers)
        assert res_create.status_code == 201
        assert res_create.json()["code"] == "CHF"

        # 4. Update currency
        update_req = {"name": "Swiss Franc Updated", "rateToUsd": "1.15"}
        res_update = client.put("/api/familyos/admin/currencies/CHF", json=update_req, headers=headers)
        assert res_update.status_code == 200
        assert res_update.json()["name"] == "Swiss Franc Updated"
        assert Decimal(str(res_update.json()["rateToUsd"])) == Decimal("1.15")

        # 5. Delete USD should fail (protected)
        res_del_usd = client.delete("/api/familyos/admin/currencies/USD", headers=headers)
        assert res_del_usd.status_code == 409

        # 6. Delete CHF should succeed
        res_del = client.delete("/api/familyos/admin/currencies/CHF", headers=headers)
        assert res_del.status_code == 200

        # 7. Public currencies list
        res_pub = client.get("/api/familyos/currencies")
        assert res_pub.status_code == 200
        pub_codes = [c["code"] for c in res_pub.json()["items"]]
        assert "USD" in pub_codes


def test_admin_users_and_families(fake_sso):
    admin_id = f"admin_{uuid4().hex[:6]}"
    token = _create_token(admin_id, "admin@test.com")
    csrf = "admin-csrf-123"

    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        client.cookies.set("csrf_token", csrf)
        headers = {"X-CSRF-Token": csrf}

        fake_sso.set_user(admin_id, role_name="super_admin")

        # 1. Create a regular user profile via /api/me/setup first
        suffix = uuid4().hex[:6]
        user_token = _create_token(f"user_{suffix}", f"test_{suffix}@test.com")
        client.cookies.set("access_token", user_token)
        res_setup = client.post(
            "/api/familyos/me/setup",
            json={"displayName": f"User {suffix}", "currencyCode": "USD", "timezone": "UTC"},
            headers=headers,
        )
        assert res_setup.status_code == 201
        profile_id = res_setup.json()["id"]

        # 2. Switch back to admin
        client.cookies.set("access_token", token)

        # 3. List users
        res_users = client.get("/api/familyos/admin/users")
        assert res_users.status_code == 200
        user_ids = [u["id"] for u in res_users.json()["items"]]
        assert profile_id in user_ids

        # 4. Patch user cap
        res_cap = client.patch(
            f"/api/familyos/admin/users/{profile_id}",
            json={"maxFamilyMemberships": 5},
            headers=headers,
        )
        assert res_cap.status_code == 200
        assert res_cap.json()["maxFamilyMemberships"] == 5

        # 5. List families
        res_fam = client.get("/api/familyos/admin/families")
        assert res_fam.status_code == 200
        assert isinstance(res_fam.json()["items"], list)
