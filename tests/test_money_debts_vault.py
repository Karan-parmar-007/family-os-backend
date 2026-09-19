import jwt
import pytest
import secrets
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from main import app
from app.config import auth_settings
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.api.routes.family.model import Family, FamilyTotalSavings


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
async def test_money_debts_and_vault_flows(db_session):
    now = datetime.now(timezone.utc)
    csrf = "test-csrf-token"

    # Head User
    u_id = uuid4()
    u = UserBase(id=u_id, email=f"head-{u_id.hex[:6]}@example.com", name="Head User", password="x")
    p = FosProfile(
        id=u_id,
        sso_user_id=str(u_id),
        email=u.email,
        display_name="Head User",
        personal_code=f"{secrets.randbelow(100000000):08d}",
        personal_currency="USD",
        max_family_memberships=2,
        setup_completed_at=now,
    )
    fam_id = uuid4()
    fam = Family(
        id=fam_id,
        name="Stark Family",
        currency="USD",
        timezone="Asia/Kolkata",
        membership_code=f"{secrets.randbelow(100000000):08d}",
        link_code=f"{secrets.randbelow(100000000):08d}",
    )
    link = UserFamilyLink(user_id=u_id, family_id=fam_id, is_family_manager=True)
    savings = FamilyTotalSavings(family_id=fam_id, origin_amount=1000.0, total_savings=1000.0)

    db_session.add_all([u, p, fam])
    await db_session.flush()
    db_session.add_all([link, savings])
    await db_session.commit()

    token = _create_token(str(u_id), u.email)
    headers = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}

    with TestClient(app) as client:
        client.cookies.set("csrf_token", csrf)

        # ----------------------------------------------------
        # 1. Money Rules & Events
        # ----------------------------------------------------
        # Create recurring income rule
        res = client.post(
            "/api/familyos/money/rules",
            json={
                "scope": "FAMILY",
                "familyId": str(fam_id),
                "kind": "INCOME",
                "name": "Consulting Retainer",
                "amount": 500.0,
                "frequency": "MONTHLY",
                "nextRunAt": now.isoformat(),
                "letEveryoneEdit": True,
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        rule_data = res.json()
        assert rule_data["name"] == "Consulting Retainer"
        assert rule_data["amount"] == 500.0

        # Create one-time expense event (Immediate pool debit)
        res = client.post(
            "/api/familyos/money/events",
            json={
                "scope": "FAMILY",
                "familyId": str(fam_id),
                "kind": "EXPENSE",
                "name": "Groceries",
                "amount": 150.0,
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text

        # Verify family total savings decremented by 150 (from 1000 to 850)
        res = client.get(f"/api/familyos/families/{fam_id}/total-savings", headers=headers)
        assert res.status_code == 200
        assert res.json()["totalSavings"] == 850.0

        # ----------------------------------------------------
        # 2. Simple Debts
        # ----------------------------------------------------
        res = client.post(
            "/api/familyos/debts",
            json={
                "scope": "FAMILY",
                "familyId": str(fam_id),
                "ownerType": "FAMILY",
                "name": "Car Loan",
                "amount": 12000.0,
                "amountPaid": 2000.0,
                "hasEmi": True,
                "emiAmount": 500.0,
                "frequency": "MONTHLY",
                "addEmiToPaid": True,
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        debt_data = res.json()
        assert debt_data["remainingAmount"] == 10000.0
        assert debt_data["hasEmi"] is True
        assert debt_data["linkedRuleId"] is not None
        debt_id = debt_data["id"]

        # Manual update of amount_paid
        res = client.patch(
            f"/api/familyos/debts/{debt_id}",
            json={"amountPaid": 12000.0},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "SETTLED"
        assert res.json()["remainingAmount"] == 0.0

        # ----------------------------------------------------
        # 3. Vault
        # ----------------------------------------------------
        # Setup PIN
        res = client.post(
            "/api/familyos/vault/setup-pin",
            json={"scope": "FAMILY", "familyId": str(fam_id), "pin": "9876"},
            headers=headers,
        )
        assert res.status_code == 200

        # Try to unlock with wrong PIN
        res = client.post(
            "/api/familyos/vault/unlock",
            json={"scope": "FAMILY", "familyId": str(fam_id), "pin": "0000"},
            headers=headers,
        )
        assert res.status_code == 401

        # Unlock with correct PIN
        res = client.post(
            "/api/familyos/vault/unlock",
            json={"scope": "FAMILY", "familyId": str(fam_id), "pin": "9876"},
            headers=headers,
        )
        assert res.status_code == 200
        vault_token = res.json()["token"]

        # Create encrypted vault item
        res = client.post(
            "/api/familyos/vault/items",
            json={
                "scope": "FAMILY",
                "familyId": str(fam_id),
                "kind": "PASSWORD",
                "title": "Netflix Family",
                "category": "Entertainment",
                "secret": "super-secret-password-123",
                "isProtected": True,
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text

        # List items without unlock header -> secret should be None
        res = client.get(f"/api/familyos/vault/items?scope=FAMILY&family_id={fam_id}", headers=headers)
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["secret"] is None
        assert res.json()["isUnlocked"] is False

        # List items WITH unlock header -> secret should be decrypted!
        headers_with_vault = {**headers, "X-Vault-Token": vault_token}
        res = client.get(f"/api/familyos/vault/items?scope=FAMILY&family_id={fam_id}", headers=headers_with_vault)
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["secret"] == "super-secret-password-123"
        assert res.json()["isUnlocked"] is True
