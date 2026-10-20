import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, status
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.api.routes.family.model import Family
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserFamilyLink
from app.api.routes.vault.model import FosVaultItem
from app.api.routes.category.category_service import CategoryService
from app.api.routes.vault.vault_schemas import VaultItemCreateRequest, VaultItemUpdateRequest
from app.api.schemas.pagination import PaginationParams
from app.core.scope import can_edit_shared
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


_AES_PREFIX = "v2:"
_AAD = b"fos-vault-secret"


def _aes_key() -> bytes:
    return hashlib.sha256(("fos-vault|" + auth_settings.vault_secret).encode()).digest()


def _legacy_xor(ciphertext: str) -> str:
    key = auth_settings.vault_secret.encode()[:32].ljust(32, b"#")
    cipher_bytes = base64.b64decode(ciphertext.encode())
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(cipher_bytes)]).decode()


def _encrypt_secret(plaintext: str) -> str:
    nonce = os.urandom(12)
    blob = nonce + AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), _AAD)
    return _AES_PREFIX + base64.b64encode(blob).decode()


def _decrypt_secret(ciphertext: str) -> str:
    if not ciphertext.startswith(_AES_PREFIX):
        return _legacy_xor(ciphertext)
    blob = base64.b64decode(ciphertext[len(_AES_PREFIX):])
    return AESGCM(_aes_key()).decrypt(blob[:12], blob[12:], _AAD).decode()


def _invalid(errors: dict[str, str]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "Validation failed", "errors": errors},
    )


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
        secret = auth_settings.vault_secret
        token = jwt.encode(payload, secret, algorithm="HS256")
        return token

    def verify_unlock_token(self, token: Optional[str], scope: str, family_id: Optional[UUID]) -> bool:
        if not token:
            return False
        try:
            secret = auth_settings.vault_secret
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

    def _category_type(self, kind: str) -> str:
        return "VAULT_PASSWORD" if kind == "PASSWORD" else "VAULT_DOCUMENT"

    async def can_edit(self, user_id: UUID, item: FosVaultItem, *, is_head: bool | None = None) -> bool:
        if item.scope == "PERSONAL":
            return item.owner_user_id == user_id
        if is_head is None:
            is_member, is_head = await self._check_family_membership(user_id, item.family_id)
            if not is_member:
                return False
        return can_edit_shared(
            actor_id=user_id,
            creator_id=item.owner_user_id,
            is_head=is_head,
            let_everyone_edit=item.let_everyone_edit,
        )

    async def list_items(
        self,
        user_id: UUID,
        scope: str,
        family_id: Optional[UUID],
        *,
        pagination: PaginationParams,
        kind: Optional[str] = None,
        category_id: Optional[UUID] = None,
        q: Optional[str] = None,
    ) -> Tuple[List[FosVaultItem], int, bool, bool, int, int]:
        """Returns (items, total, pin_configured, is_head, password_count, document_count)."""
        is_head = False
        scope = (scope or "FAMILY").upper()
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="family_id required")
            is_member, is_head = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            fam = await self.pg_session.get(Family, family_id)
            pin_configured = bool(fam and fam.vault_password_hash)
            filters = [FosVaultItem.scope == "FAMILY", FosVaultItem.family_id == family_id]
        else:
            prof = await self.pg_session.get(FosProfile, user_id)
            pin_configured = bool(prof and prof.vault_password_hash)
            filters = [FosVaultItem.scope == "PERSONAL", FosVaultItem.owner_user_id == user_id]

        # Same request as the list. FILE and older DOCUMENT rows are both documents.
        counted = (
            await self.pg_session.execute(
                select(FosVaultItem.kind, func.count())
                .where(*filters)
                .group_by(FosVaultItem.kind)
            )
        ).all()
        password_count = 0
        document_count = 0
        for kind_name, amount in counted:
            if kind_name == "PASSWORD":
                password_count = int(amount)
            else:
                document_count += int(amount)

        if kind:
            wanted = kind.upper()
            if wanted == "FILE":
                filters.append(FosVaultItem.kind.in_(("FILE", "DOCUMENT")))
            else:
                filters.append(FosVaultItem.kind == wanted)
        if category_id:
            filters.append(FosVaultItem.category_id == category_id)
        if q and q.strip():
            filters.append(func.lower(FosVaultItem.title).contains(q.strip().lower(), autoescape=True))

        total = (
            await self.pg_session.execute(select(func.count()).select_from(FosVaultItem).where(*filters))
        ).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(FosVaultItem)
                .where(*filters)
                .order_by(FosVaultItem.created_at.desc(), FosVaultItem.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), total, pin_configured, is_head, password_count, document_count

    async def _category(self, category_id: UUID | None, *, user_id: UUID, item_scope: str, family_id: UUID | None, kind: str):
        return await CategoryService(self.pg_session).require_usable(
            category_id,
            user_id=user_id,
            scope=item_scope,
            family_id=family_id,
            category_type=self._category_type(kind),
        )

    async def create_item(self, user_id: UUID, req: VaultItemCreateRequest) -> FosVaultItem:
        errors = {}
        if not req.title or not req.title.strip():
            errors["title"] = "Title is required"

        kind_clean = (req.kind or "PASSWORD").upper().strip()
        if kind_clean not in {"PASSWORD", "FILE"}:
            errors["kind"] = "Kind must be 'PASSWORD' or 'FILE'"

        scope_clean = (req.scope or "FAMILY").upper().strip()
        if scope_clean not in {"FAMILY", "PERSONAL"}:
            errors["scope"] = "Scope must be 'FAMILY' or 'PERSONAL'"
        elif scope_clean == "FAMILY" and not req.family_id:
            errors["familyId"] = "family_id is required for FAMILY scope"

        if errors:
            raise _invalid(errors)

        if scope_clean == "FAMILY":
            is_member, _ = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            party_type = (req.for_party_type or "FAMILY").upper().strip()
            target_user_id = req.for_user_id if party_type == "MEMBER" else None
            family_id = req.family_id
        else:
            party_type = "SELF"
            target_user_id = user_id
            family_id = None

        cat = await self._category(
            req.category_id, user_id=user_id, item_scope=scope_clean, family_id=family_id, kind=kind_clean
        )

        item = FosVaultItem(
            scope=scope_clean,
            family_id=family_id,
            owner_user_id=user_id,
            kind=kind_clean,
            title=req.title.strip(),
            category=cat.name if cat else None,
            category_id=cat.id if cat else None,
            let_everyone_edit=req.let_everyone_edit if scope_clean == "FAMILY" else False,
            for_party_type=party_type,
            for_user_id=target_user_id,
            document_id=req.document_id,
            is_protected=req.is_protected,
            ciphertext=_encrypt_secret(req.secret) if req.secret else None,
            file_key=req.file_key,
        )
        self.pg_session.add(item)
        await self.pg_session.commit()
        await self.pg_session.refresh(item)
        return item

    async def _get_editable(self, user_id: UUID, item_id: UUID) -> Tuple[FosVaultItem, bool]:
        """Returns (item, is_head)."""
        item = await self.pg_session.get(FosVaultItem, item_id)
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        is_head = False
        if item.scope == "FAMILY":
            is_member, is_head = await self._check_family_membership(user_id, item.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if not await self.can_edit(user_id, item, is_head=is_head):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the person who added this or a family head can change it",
            )
        return item, is_head

    async def update_item(self, user_id: UUID, item_id: UUID, req: VaultItemUpdateRequest) -> FosVaultItem:
        item, is_head = await self._get_editable(user_id, item_id)
        sent = req.model_fields_set
        if req.title is not None:
            item.title = req.title.strip()
        if "category_id" in sent:
            cat = await self._category(
                req.category_id, user_id=user_id, item_scope=item.scope, family_id=item.family_id, kind=item.kind
            )
            item.category_id = cat.id if cat else None
            item.category = cat.name if cat else None
        if item.scope == "FAMILY" and req.for_party_type is not None:
            item.for_party_type = req.for_party_type.upper()
            item.for_user_id = req.for_user_id if item.for_party_type == "MEMBER" else None
        if req.document_id is not None:
            item.document_id = req.document_id
        if req.is_protected is not None:
            item.is_protected = req.is_protected
        if req.secret is not None:
            item.ciphertext = _encrypt_secret(req.secret) if req.secret else None
        if (
            req.let_everyone_edit is not None
            and item.scope == "FAMILY"
            and req.let_everyone_edit != item.let_everyone_edit
        ):
            if user_id != item.owner_user_id and not is_head:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the person who added this or a family head can change who may edit",
                )
            item.let_everyone_edit = req.let_everyone_edit
        await self.pg_session.commit()
        await self.pg_session.refresh(item)
        return item

    async def delete_item(self, user_id: UUID, item_id: UUID) -> None:
        item, _ = await self._get_editable(user_id, item_id)
        await self.pg_session.delete(item)
        await self.pg_session.commit()
