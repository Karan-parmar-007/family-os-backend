import bcrypt
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from app.config import auth_settings


_ACCESS_AUDIENCE = "family-os-access"
_REFRESH_AUDIENCE = "family-os-refresh"
_ISSUER = "family-os-api"


def _base_payload(data: dict, audience: str) -> dict:
    """Add standard claims to a token payload."""
    payload = data.copy()
    payload["jti"] = uuid4().hex
    payload["aud"] = audience
    payload["iss"] = _ISSUER
    payload["iat"] = int(datetime.now(timezone.utc).timestamp())
    return payload


def create_access_token(data: dict) -> str:
    to_encode = _base_payload(data, _ACCESS_AUDIENCE)
    expire = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(to_encode, auth_settings.SECRET_KEY, algorithm=auth_settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    to_encode = _base_payload(data, _REFRESH_AUDIENCE)
    expire = datetime.now(timezone.utc) + timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(to_encode, auth_settings.SECRET_KEY, algorithm=auth_settings.ALGORITHM)
    return encoded_jwt


def create_forgot_password_token(data: dict) -> str:
    to_encode = _base_payload(data, "family-os-reset")
    expire = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.FORGET_PASSWORD_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(to_encode, auth_settings.SECRET_KEY, algorithm=auth_settings.ALGORITHM)
    return encoded_jwt


def create_email_verification_token(data: dict) -> str:
    to_encode = _base_payload(data, "family-os-verify")
    expire = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(to_encode, auth_settings.SECRET_KEY, algorithm=auth_settings.ALGORITHM)
    return encoded_jwt


def hash_token(raw_token: str) -> str:
    """Hash a raw token string for storage in the database."""
    import hashlib
    return hashlib.sha256(raw_token.encode()).hexdigest()


def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def decode_token(token: str, audience: Optional[str] = None) -> dict:
    """Decode and verify a JWT token. Returns payload dict or raises ValueError."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.SECRET_KEY,
            algorithms=[auth_settings.ALGORITHM],
            audience=audience,
            issuer=_ISSUER,
        )
        return payload
    except ExpiredSignatureError:
        raise ValueError("Token has expired")
    except InvalidTokenError:
        raise ValueError("Invalid token")
