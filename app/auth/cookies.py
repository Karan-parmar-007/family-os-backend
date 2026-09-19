# app/auth/cookies.py
from app.config import auth_settings

ACCESS_TOKEN_COOKIE = auth_settings.ACCESS_TOKEN_COOKIE_NAME
CSRF_TOKEN_COOKIE = auth_settings.CSRF_COOKIE_NAME
CSRF_HEADER_NAME = auth_settings.CSRF_HEADER_NAME
