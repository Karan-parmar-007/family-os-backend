import jwt
import pytest
import secrets
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from main import app
from app.config import auth_settings
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserBase


def _create_token(user_id: str, email: str, role: str = "user") -> str:
    secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "email": email,
        "role": role,
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=auth_settings.SSO_JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_family_membership_cap_and_join_flow(db_session):
    now = datetime.now(timezone.utc)
    csrf = "test-csrf-token"

    code_u1 = f"{secrets.randbelow(100000000):08d}"
    code_u2 = f"{secrets.randbelow(100000000):08d}"

    # User 1: Manager
    u1_id = uuid4()
    u1 = UserBase(id=u1_id, email=f"u1-{u1_id.hex[:6]}@example.com", name="User One", password="x")
    p1 = FosProfile(
        id=u1_id,
        sso_user_id=str(u1_id),
        email=u1.email,
        display_name="User One",
        personal_code=code_u1,
        personal_currency="USD",
        max_family_memberships=2,
        setup_completed_at=now,
    )
    db_session.add_all([u1, p1])

    # User 2: Member (cap 1 to test cap rejection)
    u2_id = uuid4()
    u2 = UserBase(id=u2_id, email=f"u2-{u2_id.hex[:6]}@example.com", name="User Two", password="x")
    p2 = FosProfile(
        id=u2_id,
        sso_user_id=str(u2_id),
        email=u2.email,
        display_name="User Two",
        personal_code=code_u2,
        personal_currency="USD",
        max_family_memberships=1,
        setup_completed_at=now,
    )
    db_session.add_all([u2, p2])
    await db_session.commit()

    token1 = _create_token(str(u1_id), u1.email)
    token2 = _create_token(str(u2_id), u2.email)

    h1 = {"Authorization": f"Bearer {token1}", "X-CSRF-Token": csrf}
    h2 = {"Authorization": f"Bearer {token2}", "X-CSRF-Token": csrf}

    with TestClient(app) as client:
        client.cookies.set("csrf_token", csrf)

        # 1. Create family 1 as User 1
        res = client.post(
            "/api/familyos/families",
            json={"name": "Alpha Family", "currency": "USD", "timezone": "Asia/Kolkata", "originAmount": 100.0},
            headers=h1,
        )
        assert res.status_code == 201, res.text
        data1 = res.json()
        fam1_id = data1["id"]
        code1 = data1["membershipCode"]
        assert len(code1) == 8

        # 2. Create family 2 as User 1 (hits cap = 2)
        res = client.post(
            "/api/familyos/families",
            json={"name": "Beta Family", "currency": "USD", "timezone": "Asia/Kolkata", "originAmount": 50.0},
            headers=h1,
        )
        assert res.status_code == 201

        # 3. Create family 3 as User 1 -> Expect 409 Conflict (cap reached)
        res = client.post(
            "/api/familyos/families",
            json={"name": "Gamma Family", "currency": "USD", "timezone": "Asia/Kolkata", "originAmount": 20.0},
            headers=h1,
        )
        assert res.status_code == 409, res.text
        assert "limit" in res.json()["detail"].lower()

        # 4. User 2 submits join request to Alpha Family using membershipCode
        res = client.post(
            "/api/familyos/families/join-request",
            json={"membershipCode": code1},
            headers=h2,
        )
        assert res.status_code == 201, res.text
        req_id = res.json()["id"]

        # 5. User 1 lists join requests
        res = client.get(
            f"/api/familyos/families/{fam1_id}/join-requests",
            headers=h1,
        )
        assert res.status_code == 200
        reqs = res.json()["items"]
        assert any(r["id"] == req_id for r in reqs)

        # 6. User 1 accepts join request -> succeeds (User 2 count becomes 1/1)
        res = client.post(
            f"/api/familyos/families/{fam1_id}/join-requests/{req_id}/accept",
            headers=h1,
        )
        assert res.status_code == 200

        # 7. User 2 tries to create a family now -> Expect 409 (User 2 cap is 1, already in 1 family)
        res = client.post(
            "/api/familyos/families",
            json={"name": "User2 Fam", "currency": "USD", "timezone": "Asia/Kolkata", "originAmount": 10.0},
            headers=h2,
        )
        assert res.status_code == 409

        # 8. Test invite flow
        res = client.post(
            f"/api/familyos/families/{fam1_id}/invites",
            json={"email": "friend@example.com"},
            headers=h1,
        )
        assert res.status_code == 201
        invite_token = res.json()["token"]

        # Check invite details public
        res = client.get(f"/api/familyos/families/invites/{invite_token}")
        assert res.status_code == 200
        assert res.json()["familyName"] == "Alpha Family"
