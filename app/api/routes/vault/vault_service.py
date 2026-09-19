import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.routes.family.model import Family
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserFamilyLink
from app.api.routes.vault.model import FosVaultItem
from app.api.routes.vault.vault_schemas import VaultItemCreateRequest
from app.config import auth_settings

logger = logging.getLogger(__name__)


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        salt, hex_dk = pin_hash.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode(), 100_000)
        return hmac.compare_digest(dk.hex(), hex_dk)
    except Exception:
        return False


def _encrypt_secret(plaintext: str) -> str:
    """Reversible cipher for vault secrets using app secret."""
    key = (auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY).encode()[:32].ljust(32, b"#")
    plain_bytes = plaintext.encode()
    cipher_bytes = bytes([b ^ key[i % len(key)] for i, b in enumerate(plain_bytes)])
    return base64.b64encode(cipher_bytes).decode()


def _decrypt_secret(ciphertext: str) -> str:
    key = (auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY).encode()[:32].ljust(32, b"#")
    cipher_bytes = base64.b64decode(ciphertext.encode())
    plain_bytes = bytes([b ^ key[i % len(key)] for i, b in enumerate(cipher_bytes)])
    return plain_bytes.decode()


class VaultService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _check_family_membership(self, user_id: UUID, family_id: UUID) -> Tuple[bool, bool]:
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        link = (await self.pg_session.execute(stmt)).scalars().first()
        if not link:
            return False, False
        return True, link.is_family_manager

    async def setup_pin(self, user_id: UUID, scope: str, family_id: Optional[UUID], pin: str) -> None:
        pin_hash = hash_pin(pin)
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, is_head = await self._check_family_membership(user_id, family_id)
            if not is_member or not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only family head can set vault PIN.")
            fam = (await self.pg_session.execute(select(Family).where(Family.id == family_id))).scalars().first()
            if not fam:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
            fam.vault_password_hash = pin_hash
        else:
            prof = (await self.pg_session.execute(select(FosProfile).where(FosProfile.id == user_id))).scalars().first()
            if not prof:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
            prof.vault_password_hash = pin_hash

        await self.pg_session.commit()

    async def unlock(self, user_id: UUID, scope: str, family_id: Optional[UUID], pin: str) -> str:
        pin_hash = None
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, _ = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            fam = (await self.pg_session.execute(select(Family).where(Family.id == family_id))).scalars().first()
            pin_hash = fam.vault_password_hash if fam else None
        else:
            prof = (await self.pg_session.execute(select(FosProfile).where(FosProfile.id == user_id))).scalars().first()
            pin_hash = prof.vault_password_hash if prof else None

        if not pin_hash:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vault PIN is not set.")

        if not verify_pin(pin, pin_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vault PIN.")

        # Create short-lived unlock token (20 minutes)
        payload = {
            "sub": str(user_id),
            "scope": scope,
            "family_id": str(family_id) if family_id else None,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=20),
            "type": "vault_unlock",
        }
        secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
        token = jwt.encode(payload, secret, algorithm="HS256")
        return token

    def verify_unlock_token(self, token: Optional[str], scope: str, family_id: Optional[UUID]) -> bool:
        if not token:
            return False
        try:
            secret = auth_settings.SSO_JWT_SECRET or auth_settings.SECRET_KEY
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            if payload.get("type") != "vault_unlock":
                return False
            if payload.get("scope") != scope:
                return False
            if scope == "FAMILY" and payload.get("family_id") != str(family_id):
                return False
            return True
        except Exception:
            return False

    async def list_items(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID],
        is_unlocked: bool,
    ) -> Tuple[List[FosVaultItem], bool]:
        pin_configured = False
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, _ = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            fam = (await self.pg_session.execute(select(Family).where(Family.id == family_id))).scalars().first()
            pin_configured = bool(fam and fam.vault_password_hash)

            stmt = select(FosVaultItem).where(
                FosVaultItem.scope == "FAMILY",
                FosVaultItem.family_id == family_id,
            ).order_by(FosVaultItem.created_at.desc())
        else:
            prof = (await self.pg_session.execute(select(FosProfile).where(FosProfile.id == user_id))).scalars().first()
            pin_configured = bool(prof and prof.vault_password_hash)

            stmt = select(FosVaultItem).where(
                FosVaultItem.scope == "PERSONAL",
                FosVaultItem.owner_user_id == user_id,
            ).order_by(FosVaultItem.created_at.desc())

        items = (await self.pg_session.execute(stmt)).scalars().all()
        return items, pin_configured

    async def create_item(self, user_id: UUID, req: VaultItemCreateRequest) -> FosVaultItem:
        errors = {}
        if not req.title or not req.title.strip():
            errors["title"] = "Title is required"
        elif len(req.title.strip()) > 255:
            errors["title"] = "Title cannot exceed 255 characters"

        if not req.category or not req.category.strip():
            errors["category"] = "Category is required"

        kind_clean = (req.kind or "PASSWORD").upper().strip()
        if kind_clean not in {"PASSWORD", "FILE"}:
            errors["kind"] = "Kind must be 'PASSWORD' or 'FILE'"

        scope_clean = (req.scope or "FAMILY").upper().strip()
        if scope_clean not in {"FAMILY", "PERSONAL"}:
            errors["scope"] = "Scope must be 'FAMILY' or 'PERSONAL'"
        elif scope_clean == "FAMILY" and not req.family_id:
            errors["familyId"] = "family_id is required for FAMILY scope"

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Validation failed", "errors": errors},
            )

        if scope_clean == "FAMILY":
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            party_type = (req.for_party_type or "FAMILY").upper().strip()
            target_user_id = req.for_user_id if party_type == "MEMBER" else None
        else:
            party_type = "SELF"
            target_user_id = user_id
            req.family_id = None

        ciphertext = None
        if req.secret:
            ciphertext = _encrypt_secret(req.secret)

        item = FosVaultItem(
            scope=scope_clean,
            family_id=req.family_id,
            owner_user_id=user_id,
            kind=kind_clean,
            title=req.title.strip(),
            category=req.category.strip(),
            for_party_type=party_type,
            for_user_id=target_user_id,
            document_id=req.document_id,
            is_protected=req.is_protected,
            ciphertext=ciphertext,
            file_key=req.file_key,
        )
        self.pg_session.add(item)
        await self.pg_session.commit()
        await self.pg_session.refresh(item)
        return item

    async def delete_item(self, user_id: UUID, item_id: UUID) -> None:
        item = (await self.pg_session.execute(select(FosVaultItem).where(FosVaultItem.id == item_id))).scalars().first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

        if item.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, item.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            if item.owner_user_id != user_id and not is_head:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            if item.owner_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        await self.pg_session.delete(item)
        await self.pg_session.commit()
