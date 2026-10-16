# app/auth/sso.py
"""Configure the shared karan_sso SDK from Family OS settings."""
from __future__ import annotations

from karan_sso import SsoSettings
from karan_sso.fastapi import SsoAuth, configure

from app.config import auth_settings

sso_settings: SsoSettings = auth_settings.sso_settings()


def configure_sso() -> SsoAuth:
    """Install the default SDK instance used by the auth dependencies."""
    return configure(sso_settings)
