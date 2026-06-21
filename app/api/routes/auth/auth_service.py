import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import EmailStr
from pymongo.asynchronous.database import AsyncDatabase
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth.auth_schemas import ChangePasswordRequest
from app.api.routes.auth.model import (
    EmailChangeToken,
    EmailVerificationToken,
    FamilyAccountSetupToken,
    ForgetPasswordToken,
    RefreshToken,
    ResetPasswordToken,
)
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.config import auth_settings
from app.utils.email_service import email_service
from app.utils.security_and_auth import (
    REFRESH_AUDIENCE,
    create_access_token,
    create_email_verification_token,
    create_family_invite_token,
    create_forgot_password_token,
    create_refresh_token,
    decode_token,
    generate_csrf_token,
    generate_otp,
    hash_password,
    hash_token,
    verify_password,
)

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self,
        pg_session: AsyncSession,
        mongo_db: AsyncDatabase,
    ) -> None:
        self.pg_session = pg_session
        self.mongo_db = mongo_db

    async def signup(self, email: EmailStr, password: str, name: str) -> tuple[str, str, str]:
        existing = await self._get_user_by_email(email)
        if existing is not None:
            raise ValueError("Email already registered")

        hashed = hash_password(password)
        user = UserBase(email=email, password=hashed, name=name)
        self.pg_session.add(user)
        await self.pg_session.commit()
        await self.pg_session.refresh(user)

        verification_token = create_email_verification_token({"sub": str(user.id)})
        await self._save_verification_token(user.id, verification_token)
        await email_service.send_verification_email(email, verification_token)

        access_token = create_access_token({"sub": str(user.id), "email": email})
        refresh_token_val = create_refresh_token({"sub": str(user.id)})
        await self._save_refresh_token(user.id, refresh_token_val)
        csrf_token = generate_csrf_token()

        return access_token, refresh_token_val, csrf_token

    async def login(self, email: EmailStr, password: str) -> tuple[str, str, str]:
        user = await self._get_user_by_email(email)
        if user is None or not verify_password(password, user.password):
            raise ValueError("Invalid email or password")
        if not user.is_active:
            raise ValueError("User account is inactive")

        access_token = create_access_token({"sub": str(user.id), "email": email})
        refresh_token_val = create_refresh_token({"sub": str(user.id)})
        await self._save_refresh_token(user.id, refresh_token_val)
        csrf_token = generate_csrf_token()

        return access_token, refresh_token_val, csrf_token

    async def refresh_token(self, refresh_token_val: str) -> tuple[str, str, str]:
        try:
            payload = decode_token(refresh_token_val, audience=REFRESH_AUDIENCE)
            user_id_str: str = payload.get("sub")
            jti: str = payload.get("jti")
            if user_id_str is None or jti is None:
                raise ValueError("Invalid token")
        except ValueError:
            raise ValueError("Invalid or expired refresh token")

        hashed = hash_token(refresh_token_val)

        stmt = select(RefreshToken).where(
            RefreshToken.token == hashed,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        result = await self.pg_session.execute(stmt)
        stored = result.scalar_one_or_none()
        if stored is None:
            await self._revoke_all_tokens(UUID(user_id_str))
            raise ValueError("Refresh token not found or expired")

        await self.pg_session.delete(stored)
        await self.pg_session.commit()

        user = await self._get_user_by_id(UUID(user_id_str))
        if user is None or not user.is_active:
            raise ValueError("User not found or inactive")

        new_access = create_access_token({"sub": str(user.id), "email": user.email})
        new_refresh = create_refresh_token({"sub": str(user.id)})
        await self._save_refresh_token(user.id, new_refresh)
        csrf_token = generate_csrf_token()

        return new_access, new_refresh, csrf_token

    async def logout(self, refresh_token_val: str) -> None:
        hashed = hash_token(refresh_token_val)
        stmt = select(RefreshToken).where(RefreshToken.token == hashed)
        result = await self.pg_session.execute(stmt)
        stored = result.scalar_one_or_none()
        if stored is not None:
            await self._revoke_all_tokens(stored.user_id)

    async def _revoke_all_tokens(self, user_id: UUID) -> None:
        stmt = delete(RefreshToken).where(RefreshToken.user_id == user_id)
        await self.pg_session.execute(stmt)
        await self.pg_session.commit()

    async def forget_password(self, email: EmailStr) -> None:
        user = await self._get_user_by_email(email)
        if user is None:
            return
        token = create_forgot_password_token({"sub": str(user.id)})
        await self._save_forget_token(user.id, token)
        await email_service.send_password_reset_email(email, token)

    async def reset_password(self, token: str, new_password: str) -> None:
        try:
            payload = decode_token(token, audience="family-os-reset")
            user_id_str: str = payload.get("sub")
            if user_id_str is None:
                raise ValueError("Invalid token")
        except ValueError:
            raise ValueError("Invalid or expired reset token")

        user = await self._get_user_by_id(UUID(user_id_str))
        if user is None:
            raise ValueError("User not found")

        user.password = hash_password(new_password)
        await self.pg_session.commit()

        stmt = delete(ForgetPasswordToken).where(ForgetPasswordToken.user_id == user.id)
        await self.pg_session.execute(stmt)
        await self.pg_session.commit()

    async def change_password(self, user: UserBase, req: ChangePasswordRequest) -> None:
        if not verify_password(req.old_password, user.password):
            raise ValueError("Current password is incorrect")
        user.password = hash_password(req.new_password)
        await self.pg_session.commit()

    async def verify_email(self, token: str) -> None:
        try:
            payload = decode_token(token, audience="family-os-verify")
            user_id_str: str = payload.get("sub")
            if user_id_str is None:
                raise ValueError("Invalid token")
        except ValueError:
            raise ValueError("Invalid or expired verification token")

        user = await self._get_user_by_id(UUID(user_id_str))
        if user is None:
            raise ValueError("User not found")
        if user.is_email_verified:
            raise ValueError("Email already verified")

        user.is_email_verified = True
        await self.pg_session.commit()

        stmt = delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.token == token,
        )
        await self.pg_session.execute(stmt)
        await self.pg_session.commit()

    async def request_email_change(
        self,
        user: UserBase,
        new_email: EmailStr,
        current_password: str,
    ) -> None:
        if not verify_password(current_password, user.password):
            raise ValueError("Current password is incorrect")
        if new_email == user.email:
            raise ValueError("New email must differ from current email")

        existing = await self._get_user_by_email(new_email)
        if existing is not None:
            raise ValueError("Email already registered")

        otp = generate_otp()
        await self._save_email_change_otp(user.id, new_email, otp)
        await email_service.send_email_change_otp(new_email, otp)

    async def verify_email_change_otp(
        self,
        user: UserBase,
        new_email: EmailStr,
        otp: str,
    ) -> None:
        stmt = select(EmailChangeToken).where(
            EmailChangeToken.user_id == user.id,
            EmailChangeToken.new_email == new_email,
            EmailChangeToken.expires_at > datetime.now(timezone.utc),
        )
        result = await self.pg_session.execute(stmt)
        stored = result.scalar_one_or_none()
        if stored is None:
            raise ValueError("OTP expired or no pending email change request")

        if not secrets.compare_digest(hash_token(otp), stored.otp_hash):
            raise ValueError("Invalid OTP")

        existing = await self._get_user_by_email(new_email)
        if existing is not None and existing.id != user.id:
            raise ValueError("Email already registered")

        user.email = new_email
        user.is_email_verified = True
        await self.pg_session.commit()

        stmt = delete(EmailChangeToken).where(EmailChangeToken.user_id == user.id)
        await self.pg_session.execute(stmt)
        await self.pg_session.commit()

    async def _get_user_by_email(self, email: EmailStr) -> UserBase | None:
        stmt = select(UserBase).where(UserBase.email == email)
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, user_id: UUID) -> UserBase | None:
        stmt = select(UserBase).where(UserBase.id == user_id)
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def _save_refresh_token(self, user_id: UUID, token_val: str) -> None:
        expires = datetime.now(timezone.utc) + timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS)
        rt = RefreshToken(user_id=user_id, token=hash_token(token_val), expires_at=expires)
        self.pg_session.add(rt)
        await self.pg_session.commit()

    async def _save_verification_token(self, user_id: UUID, token_val: str) -> None:
        expires = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES)
        vt = EmailVerificationToken(user_id=user_id, token=token_val, expires_at=expires)
        self.pg_session.add(vt)
        await self.pg_session.commit()

    async def _save_forget_token(self, user_id: UUID, token_val: str) -> None:
        expires = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.FORGET_PASSWORD_TOKEN_EXPIRE_MINUTES)
        ft = ForgetPasswordToken(user_id=user_id, token=token_val, expires_at=expires)
        self.pg_session.add(ft)
        await self.pg_session.commit()

    async def _save_email_change_otp(self, user_id: UUID, new_email: str, otp: str) -> None:
        expires = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.EMAIL_CHANGE_OTP_EXPIRE_MINUTES)
        await self.pg_session.execute(delete(EmailChangeToken).where(EmailChangeToken.user_id == user_id))
        ect = EmailChangeToken(
            user_id=user_id,
            new_email=new_email,
            otp_hash=hash_token(otp),
            expires_at=expires,
        )
        self.pg_session.add(ect)
        await self.pg_session.commit()

    async def invite_member(
        self,
        inviter_id: UUID,
        family_id: UUID,
        email: EmailStr,
    ) -> None:
        """
        Existing user  → add to family immediately, send notification email.
        New user       → create FamilyAccountSetupToken, send setup email.
        """
        existing_user = await self._get_user_by_email(email)

        if existing_user is not None:
            stmt = select(UserFamilyLink).where(
                UserFamilyLink.user_id == existing_user.id,
                UserFamilyLink.family_id == family_id,
            )
            result = await self.pg_session.execute(stmt)
            if result.scalar_one_or_none() is not None:
                raise ValueError("User is already a member of this family")

            link = UserFamilyLink(
                user_id=existing_user.id,
                family_id=family_id,
                is_family_manager=False,
            )
            self.pg_session.add(link)
            await self.pg_session.commit()

            await email_service.send_family_added_email(email)
        else:
            # Guard against duplicate pending invites for the same (email, family)
            stmt = select(FamilyAccountSetupToken).where(
                FamilyAccountSetupToken.email == email,
                FamilyAccountSetupToken.family_id == family_id,
                FamilyAccountSetupToken.expires_at > datetime.now(timezone.utc),
            )
            result = await self.pg_session.execute(stmt)
            if result.scalar_one_or_none() is not None:
                raise ValueError("A pending invite already exists for this email in this family")

            token = create_family_invite_token({"email": email})
            expires = datetime.now(timezone.utc) + timedelta(days=auth_settings.FAMILY_INVITE_TOKEN_EXPIRE_DAYS)
            setup_token = FamilyAccountSetupToken(
                email=email,
                token=hash_token(token),
                family_id=family_id,
                invited_by=inviter_id,
                expires_at=expires,
            )
            self.pg_session.add(setup_token)
            await self.pg_session.commit()

            await email_service.send_account_setup_email(email, token)

    async def complete_account_setup(
        self,
        email: str,
        token: str,
        name: str,
        password: str,
    ) -> None:
        """
        Complete account setup for an invited new user.
        If the user signed up on the main site between invite and setup,
        we just link them to the family and discard the token.
        """
        try:
            payload = decode_token(token, audience="family-os-invite")
            token_email: str | None = payload.get("email")
            if not token_email:
                raise ValueError("Invalid token")
        except ValueError:
            raise ValueError("Invalid or expired invite token")

        if token_email.lower() != email.lower():
            raise ValueError("Email does not match the invite token")

        stmt = select(FamilyAccountSetupToken).where(
            FamilyAccountSetupToken.email == email,
            FamilyAccountSetupToken.token == hash_token(token),
            FamilyAccountSetupToken.expires_at > datetime.now(timezone.utc),
        )
        result = await self.pg_session.execute(stmt)
        setup_token = result.scalar_one_or_none()
        if setup_token is None:
            raise ValueError("Invalid or expired invite token")

        existing_user = await self._get_user_by_email(email)
        if existing_user is not None:
            # User signed up via main website after the invite was sent
            stmt = select(UserFamilyLink).where(
                UserFamilyLink.user_id == existing_user.id,
                UserFamilyLink.family_id == setup_token.family_id,
            )
            result = await self.pg_session.execute(stmt)
            if result.scalar_one_or_none() is None:
                self.pg_session.add(UserFamilyLink(
                    user_id=existing_user.id,
                    family_id=setup_token.family_id,
                    is_family_manager=False,
                ))
            await self.pg_session.delete(setup_token)
            await self.pg_session.commit()
            return

        hashed_pw = hash_password(password)
        new_user = UserBase(
            email=email,
            password=hashed_pw,
            name=name,
            is_email_verified=True,
        )
        self.pg_session.add(new_user)
        await self.pg_session.flush()  # populate new_user.id without committing

        self.pg_session.add(UserFamilyLink(
            user_id=new_user.id,
            family_id=setup_token.family_id,
            is_family_manager=False,
        ))
        await self.pg_session.delete(setup_token)
        await self.pg_session.commit()
