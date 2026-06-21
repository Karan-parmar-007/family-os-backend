from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserMeUpdate(BaseModel):
    name: str | None = None


class RequestEmailChange(BaseModel):
    new_email: EmailStr
    current_password: str


class VerifyEmailChangeOtp(BaseModel):
    new_email: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class UserMeResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    is_active: bool
    is_premium_user: bool
    is_email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
