# app/config.py
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
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RESET_PASSWORD_TOKEN_EXPIRE_MINUTES: int = 15
    FORGET_PASSWORD_TOKEN_EXPIRE_MINUTES: int = 15
    EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = 15
    CSRF_SECRET_KEY: str = ""

    model_config = _base_config

    @property
    def _csrf_secret(self) -> str:
        return self.CSRF_SECRET_KEY or self.SECRET_KEY


class EmailSettings(BaseSettings):
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM_EMAIL: str
    SMTP_FROM_NAME: str = "Faminly OS"
    FRONTEND_URL: str = "http://localhost:5173"

    model_config = _base_config


auth_settings = AuthSettings() # type: ignore
db_settings = DatabaseSettings() # type: ignore
email_settings = EmailSettings() # type: ignore