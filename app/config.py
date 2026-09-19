# app/config.py
import base64

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
    SECRET_KEY: str = ""
    # SSO auth
    SSO_JWT_SECRET: str = ""
    SSO_JWT_ALGORITHM: str = "HS256"
    SSO_BASE_URL: str = "http://localhost:8000/api"
    SSO_FRONTEND_URL: str = "http://localhost:5173"
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    ENVIRONMENT: str = "development"

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RESET_PASSWORD_TOKEN_EXPIRE_MINUTES: int = 15
    FORGET_PASSWORD_TOKEN_EXPIRE_MINUTES: int = 15
    EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = 15
    EMAIL_CHANGE_OTP_EXPIRE_MINUTES: int = 10
    CSRF_SECRET_KEY: str = ""
    FAMILY_INVITE_TOKEN_EXPIRE_DAYS: int = 2
    
    # New Auth & CSRF Settings
    APP_NAME: str = "family-os"
    AUTH_AUDIENCE_ACCESS: str = "family-os-access"
    AUTH_AUDIENCE_REFRESH: str = "family_os_refresh"
    AUTH_ISSUER: str = "family-os-api"
    CSRF_COOKIE_SAMESITE: str = "lax"

    model_config = _base_config

    @property
    def csrf_secret(self) -> str:
        """CSRF signing secret — falls back to SECRET_KEY when unset."""
        return self.CSRF_SECRET_KEY or self.SECRET_KEY


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
        "https://familyos.karanparmar.in,https://auth.karanparmar.in"
    )

    model_config = _base_config

    @property
    def allowed_origins(self) -> list[str]:
        if not self.CORS_ALLOWED_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]


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
