# app/api/routes/profile/profile_schemas.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


ALLOWED_TIMEZONES = {
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "US/Eastern",
    "US/Central",
    "US/Mountain",
    "US/Pacific",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "UTC",
}


class ProfileSetupRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    display_name: str
    currency_code: str = "USD"
    timezone: str = "Asia/Kolkata"
    personal_savings_origin: str = "0"

    @field_validator("display_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("displayName must not be blank")
        if len(v) > 100:
            raise ValueError("displayName must be 100 characters or fewer")
        return v

    @field_validator("currency_code")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("currencyCode must be a 3-letter ISO code")
        return v

    @field_validator("timezone")
    @classmethod
    def tz_allowed(cls, v: str) -> str:
        v = v.strip()
        if v not in ALLOWED_TIMEZONES:
            raise ValueError(
                f"timezone must be one of: {sorted(ALLOWED_TIMEZONES)}"
            )
        return v

    @field_validator("personal_savings_origin")
    @classmethod
    def savings_non_negative(cls, v: str) -> str:
        try:
            val = float(v or "0")
        except ValueError:
            raise ValueError("personalSavingsOrigin must be a number")
        if val < 0:
            raise ValueError("personalSavingsOrigin must be >= 0")
        return v or "0"


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    display_name: str | None = None
    currency_code: str | None = None
    timezone: str | None = None

    @field_validator("display_name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("displayName must not be blank")
        if len(v) > 100:
            raise ValueError("displayName must be 100 characters or fewer")
        return v

    @field_validator("currency_code")
    @classmethod
    def currency_uppercase(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("currencyCode must be a 3-letter ISO code")
        return v

    @field_validator("timezone")
    @classmethod
    def tz_allowed(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v not in ALLOWED_TIMEZONES:
            raise ValueError(
                f"timezone must be one of: {sorted(ALLOWED_TIMEZONES)}"
            )
        return v


class ProfileResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    id: UUID
    sso_user_id: str
    email: str
    display_name: str
    personal_currency: str
    timezone: str
    personal_code: str
    max_family_memberships: int
    is_active: bool
    setup_completed_at: datetime
    created_at: datetime
