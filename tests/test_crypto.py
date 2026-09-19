"""Tests for crypto encrypt/decrypt round-trip (Family System V2)."""

from app.core import crypto


def test_encrypt_decrypt_round_trip_with_flag_off(monkeypatch):
    monkeypatch.setattr(crypto.feature_settings, "FEATURE_ENCRYPTION", False)
    plain = b"family document bytes"
    blob = crypto.encrypt(plain)
    assert crypto.decrypt(blob) == plain


def test_maybe_decrypt_legacy_plaintext(monkeypatch):
    monkeypatch.setattr(crypto.feature_settings, "FEATURE_ENCRYPTION", True)
    from app.api.routes.document.document_service import _maybe_decrypt

    plain = b"legacy-unencrypted-blob"
    assert _maybe_decrypt(plain) == plain
