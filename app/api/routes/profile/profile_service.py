# app/api/routes/profile/profile_service.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.profile.model import FosProfile
from app.api.routes.profile.profile_schemas import (
    ProfileSetupRequest,
    ProfileUpdateRequest,
)

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def get_by_sso_id(self, sso_user_id: str) -> FosProfile | None:
        stmt = select(FosProfile).where(FosProfile.sso_user_id == sso_user_id)
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, profile_id: UUID) -> FosProfile | None:
        stmt = select(FosProfile).where(FosProfile.id == profile_id)
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_profile(
        self,
        sso_user_id: str,
        email: str,
        req: ProfileSetupRequest,
    ) -> FosProfile:
        """
        Create a FosProfile for a first-time user.
        Raises ValueError if profile already exists (caller should 409).
        Does NOT set savings origin — caller handles ledger after commit.
        """
        existing = await self.get_by_sso_id(sso_user_id)
        if existing is not None:
            raise ValueError("profile_exists")

        profile = FosProfile(
            sso_user_id=sso_user_id,
            email=email,
            display_name=req.display_name,
            personal_currency=req.currency_code,
            timezone=req.timezone,
            setup_completed_at=datetime.now(timezone.utc),
        )
        self.pg_session.add(profile)
        await self.pg_session.flush()  # get profile.id without committing
        return profile

    async def update_profile(
        self,
        profile: FosProfile,
        req: ProfileUpdateRequest,
    ) -> FosProfile:
        if req.display_name is not None:
            profile.display_name = req.display_name
        if req.currency_code is not None:
            profile.personal_currency = req.currency_code
        if req.timezone is not None:
            profile.timezone = req.timezone
        await self.pg_session.commit()
        await self.pg_session.refresh(profile)
        return profile
