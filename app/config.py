# app/config.py
import base64
from urllib.parse import urlparse

from karan_sso import SsoSettings
from pydantic_settings import BaseSettings, SettingsConfigDict

_base_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_ignore_empty=True,
    extra="ignore"

)

class DatabaseSettings(BaseSettings):
    """Database settings."""
    POSTGRES_SERVER: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_ECHO: bool = False

    
    MONGO_URI: str 
    MONGO_DB_NAME: str

    GARAGE_ENDPOINT_URL: str
    GARAGE_ACCESS_KEY: str
    GARAGE_SECRET_KEY: str
    GARAGE_BUCKET_NAME: str
    GARAGE_REGION_NAME: str

    model_config = _base_config

    @property
    def POSTGRES_URL(self) -> str:
        """Construct the PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


class AuthSettings(BaseSettings):
    ENVIRONMENT: str = "development"

    # SSO (shared karan_sso SDK; see karan_sso/ and the SSO contract)
    # Internal URL of the SSO API, e.g. http://sso-backend:8000/api
    SSO_BASE_URL: str = "http://localhost:8000/api"
    # Public issuer (JWT `iss`), e.g. https://auth.karanparmar.in/api/auth. Empty = don't check.
    SSO_ISSUER: str = ""
    SSO_AUDIENCE: str = "karanparmar-apps"
    # Turn on once SSO sets JWT_AUDIENCE.
    SSO_REQUIRE_AUDIENCE: bool = False
    # This app's id in SSO (app-scoped roles, e.g. {"familyos": ["admin"]}).
    SSO_APP_ID: str = "familyos"
    # Legacy HS256 shared secret — accepted only during the RS256 rollout, then remove.
    SSO_JWT_SECRET: str = ""
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # Vault secret encryption / unlock-token signing. Never used for SSO tokens.
    # Set VAULT_SECRET_KEY to the current SSO_JWT_SECRET value before removing
    # SSO_JWT_SECRET, otherwise existing vault secrets can't be decrypted.
    VAULT_SECRET_KEY: str = ""
    SECRET_KEY: str = ""

    EMAIL_CHANGE_OTP_EXPIRE_MINUTES: int = 10
    FAMILY_INVITE_TOKEN_EXPIRE_DAYS: int = 2

    model_config = _base_config

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def vault_secret(self) -> str:
        return self.VAULT_SECRET_KEY or self.SSO_JWT_SECRET or self.SECRET_KEY

    def sso_settings(self) -> SsoSettings:
        """SDK settings; anything not set here is still read from env by the SDK."""
        return SsoSettings(
            SSO_BASE_URL=self.SSO_BASE_URL,
            SSO_ISSUER=self.SSO_ISSUER,
            SSO_AUDIENCE=self.SSO_AUDIENCE,
            SSO_REQUIRE_AUDIENCE=self.SSO_REQUIRE_AUDIENCE,
            SSO_JWT_SECRET=self.SSO_JWT_SECRET,
            SSO_APP_ID=self.SSO_APP_ID,
            ACCESS_TOKEN_COOKIE_NAME=self.ACCESS_TOKEN_COOKIE_NAME,
            CSRF_COOKIE_NAME=self.CSRF_COOKIE_NAME,
            CSRF_HEADER_NAME=self.CSRF_HEADER_NAME,
        )


class EmailSettings(BaseSettings):
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM_EMAIL: str
    SMTP_FROM_NAME: str = "Faminly OS"
    FRONTEND_URL: str = "http://localhost:1577"

    model_config = _base_config


class CorsSettings(BaseSettings):
    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:5173,http://localhost:1577,"
        "https://familyos.karanparmar.in"
    )
    ENVIRONMENT: str = "development"

    model_config = _base_config

    @property
    def allowed_origins(self) -> list[str]:
        """Explicit origins only; localhost/127.0.0.1 are dropped in production."""
        origins = [o.strip().rstrip("/") for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        origins = [o for o in origins if o != "*"]
        if self.ENVIRONMENT.strip().lower() == "production":
            origins = [o for o in origins if not _is_local_origin(o)]
        return origins


def _is_local_origin(origin: str) -> bool:
    host = urlparse(origin).hostname or ""
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".localhost")


class FeatureSettings(BaseSettings):
    FEATURE_SUBFAMILIES: bool = True
    FEATURE_SHARING: bool = True
    FEATURE_TRANSFERS: bool = True
    FEATURE_SCHEDULER: bool = False
    FEATURE_NOTIFICATIONS: bool = True
    FEATURE_ENCRYPTION: bool = False
    OWNERSHIP_STRICT: bool = True

    model_config = _base_config


class SchedulerSettings(BaseSettings):
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TICK_MINUTES: int = 1
    JOB_MAX_RETRIES: int = 3
    JOB_DEFAULT_DELAY_DAYS: int = 3
    JOB_ADVISORY_LOCK_KEY: int = 8675309

    model_config = _base_config


class CryptoSettings(BaseSettings):
    ENCRYPTION_KEYS: str = ""
    ENCRYPTION_ACTIVE_KEY_ID: str = "v1"
    ENCRYPT_DOCUMENTS: bool = True

    model_config = _base_config

    def encryption_key_bytes(self, key_id: str | None = None) -> bytes:
        kid = key_id or self.ENCRYPTION_ACTIVE_KEY_ID
        if not self.ENCRYPTION_KEYS:
            raise ValueError("ENCRYPTION_KEYS not configured")
        for part in self.ENCRYPTION_KEYS.split(","):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            if k == kid:
                return base64.b64decode(v)
        raise ValueError(f"Unknown encryption key id: {kid}")


auth_settings = AuthSettings() # type: ignore
db_settings = DatabaseSettings() # type: ignore
email_settings = EmailSettings() # type: ignore
cors_settings = CorsSettings() # type: ignore
feature_settings = FeatureSettings() # type: ignore
scheduler_settings = SchedulerSettings() # type: ignore
crypto_settings = CryptoSettings() # type: ignore
