from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class VerifyEmailRequest(BaseModel):
    token: str


class InviteMemberRequest(BaseModel):
    email: EmailStr
    family_id: UUID


class AccountSetupRequest(BaseModel):
    """Complete account setup via invite link (new users only)."""
    email: EmailStr
    token: str
    name: str
    password: str = Field(min_length=8)


class MessageResponse(BaseModel):
    message: str
