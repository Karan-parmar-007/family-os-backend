"""App-managed encryption at rest (Family System V2)."""

import base64
import os
from decimal import Decimal
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import LargeBinary, TypeDecorator

from app.config import crypto_settings, feature_settings


def _get_active_key() -> tuple[str, bytes]:
    key_id = crypto_settings.ENCRYPTION_ACTIVE_KEY_ID
    raw = crypto_settings.encryption_key_bytes(key_id)
    return key_id, raw


def encrypt(plaintext: bytes, *, aad: bytes = b"") -> bytes:
    if not feature_settings.FEATURE_ENCRYPTION:
        return plaintext
    key_id, key = _get_active_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    kid_byte = key_id.encode("utf-8")
    return bytes([len(kid_byte)]) + kid_byte + nonce + ciphertext


def decrypt(blob: bytes, *, aad: bytes = b"") -> bytes:
    if not feature_settings.FEATURE_ENCRYPTION:
        return blob
    kid_len = blob[0]
    key_id = blob[1 : 1 + kid_len].decode("utf-8")
    nonce = blob[1 + kid_len : 1 + kid_len + 12]
    ciphertext = blob[1 + kid_len + 12 :]
    key = crypto_settings.encryption_key_bytes(key_id)
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


class EncryptedString(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return encrypt(value.encode("utf-8"))

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return decrypt(value).decode("utf-8")


class EncryptedNumeric(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return encrypt(str(value).encode("utf-8"))

    def process_result_value(self, value: bytes | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(decrypt(value).decode("utf-8"))
