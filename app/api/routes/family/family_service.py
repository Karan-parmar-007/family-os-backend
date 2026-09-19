import logging
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.api.routes.family.model import (
    Family,
    FamilyTotalSavings,
    FosFamilyJoinRequest,
    FosFamilyInvite,
    SavingsLedger,
    UserGlobalPersonalSavings,
    generate_code,
)
from app.api.routes.profile.model import FosProfile
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.api.schemas.pagination import PaginationParams
from app.core.constants import LEDGER_IN, LEDGER_SOURCE_ORIGIN, POOL_FAMILY, POOL_PERSONAL
from app.core.currency_service import convert

logger = logging.getLogger(__name__)


class FamilyService:
    def __init__(self, pg_session: AsyncSession, mongo_db=None, garage_client=None):
        self.pg_session = pg_session
        self.mongo_db = mongo_db
        self.garage_client = garage_client

    async def get_user_membership_stats(self, user_id: UUID) -> Tuple[int, int]:
        """Return (current_count, max_family_memberships)."""
        count_query = select(func.count()).where(UserFamilyLink.user_id == user_id)
        count_res = await self.pg_session.execute(count_query)
        current_count = count_res.scalar() or 0

        prof_query = select(FosProfile).where(FosProfile.id == user_id)
        prof_res = await self.pg_session.execute(prof_query)
        profile = prof_res.scalars().first()
        max_memberships = profile.max_family_memberships if profile else 2
        return current_count, max_memberships

    async def list_user_families(self, user_id: UUID) -> List[Tuple[Family, UserFamilyLink]]:
        stmt = (
            select(Family, UserFamilyLink)
            .join(UserFamilyLink, Family.id == UserFamilyLink.family_id)
            .where(UserFamilyLink.user_id == user_id)
        )
        res = await self.pg_session.execute(stmt)
        return res.all()

    async def create_family(
        self,
        user_id: UUID,
        family_name: str,
        currency: str,
        timezone_str: str,
        origin_amount: float,
    ) -> Family:
        # Check membership cap
        current_count, max_memberships = await self.get_user_membership_stats(user_id)
        if current_count >= max_memberships:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You have reached your maximum family memberships limit ({current_count}/{max_memberships}).",
            )

        # Retrieve user profile to check currency conversion
        prof_res = await self.pg_session.execute(select(FosProfile).where(FosProfile.id == user_id))
        profile = prof_res.scalars().first()
        user_currency = profile.personal_currency if profile else "USD"

        # Convert origin amount if typed in user currency
        conv_res = await convert(
            self.pg_session,
            Decimal(str(origin_amount)),
            base=user_currency,
            quote=currency,
        )
        converted_origin = conv_res.converted

        family = Family(
            name=family_name.strip(),
            currency=currency.upper(),
            timezone=timezone_str,
            membership_code=generate_code(),
            link_code=generate_code(),
        )
        self.pg_session.add(family)
        await self.pg_session.flush()

        # Link user as head
        link = UserFamilyLink(
            user_id=user_id,
            family_id=family.id,
            is_family_manager=True,
        )
        self.pg_session.add(link)

        # Family total savings (ORIGIN)
        savings = FamilyTotalSavings(
            family_id=family.id,
            origin_amount=converted_origin,
            total_savings=converted_origin,
        )
        self.pg_session.add(savings)

        # Ledger row
        now = datetime.now(timezone.utc)
        ledger_entry = SavingsLedger(
            pool_type=POOL_FAMILY,
            family_id=family.id,
            user_id=user_id,
            amount=converted_origin,
            direction=LEDGER_IN,
            source_type=LEDGER_SOURCE_ORIGIN,
            description="Initial Family Origin Pool",
            occurred_at=now,
        )
        self.pg_session.add(ledger_entry)

        await self.pg_session.commit()
        await self.pg_session.refresh(family)
        return family

    async def update_family(
        self,
        family_id: UUID,
        name: Optional[str] = None,
        currency: Optional[str] = None,
        timezone_str: Optional[str] = None,
    ) -> Family:
        stmt = select(Family).where(Family.id == family_id)
        res = await self.pg_session.execute(stmt)
        family = res.scalars().first()
        if not family:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")

        if name is not None:
            family.name = name.strip()
        if currency is not None:
            family.currency = currency.upper()
        if timezone_str is not None:
            family.timezone = timezone_str

        await self.pg_session.commit()
        await self.pg_session.refresh(family)
        return family

    async def get_family_members(self, family_id: UUID) -> List[Tuple[FosProfile, UserFamilyLink]]:
        stmt = (
            select(FosProfile, UserFamilyLink)
            .join(UserFamilyLink, FosProfile.id == UserFamilyLink.user_id)
            .where(UserFamilyLink.family_id == family_id)
            .order_by(UserFamilyLink.created_at.asc())
        )
        res = await self.pg_session.execute(stmt)
        return list(res.all())

    async def get_family_total_savings(self, family_id: UUID) -> Optional[FamilyTotalSavings]:
        stmt = select(FamilyTotalSavings).where(FamilyTotalSavings.family_id == family_id)
        res = await self.pg_session.execute(stmt)
        return res.scalars().first()

    async def list_family_savings_ledger(
        self, family_id: UUID, pagination: PaginationParams
    ) -> Tuple[List[SavingsLedger], int]:
        count_stmt = select(func.count()).where(
            SavingsLedger.family_id == family_id,
            SavingsLedger.pool_type == POOL_FAMILY,
        )
        total = (await self.pg_session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(SavingsLedger)
            .where(
                SavingsLedger.family_id == family_id,
                SavingsLedger.pool_type == POOL_FAMILY,
            )
            .order_by(SavingsLedger.occurred_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        items = (await self.pg_session.execute(stmt)).scalars().all()
        return items, total

    async def get_personal_savings(self, user_id: UUID) -> Optional[UserGlobalPersonalSavings]:
        stmt = select(UserGlobalPersonalSavings).where(UserGlobalPersonalSavings.user_id == user_id)
        res = await self.pg_session.execute(stmt)
        return res.scalars().first()

    async def list_personal_savings_ledger(
        self, user_id: UUID, pagination: PaginationParams
    ) -> Tuple[List[SavingsLedger], int]:
        count_stmt = select(func.count()).where(
            SavingsLedger.user_id == user_id,
            SavingsLedger.pool_type == POOL_PERSONAL,
        )
        total = (await self.pg_session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(SavingsLedger)
            .where(
                SavingsLedger.user_id == user_id,
                SavingsLedger.pool_type == POOL_PERSONAL,
            )
            .order_by(SavingsLedger.occurred_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        items = (await self.pg_session.execute(stmt)).scalars().all()
        return items, total

    # --- Membership join requests ---

    async def create_join_request(self, user_id: UUID, membership_code: str) -> FosFamilyJoinRequest:
        stmt = select(Family).where(Family.membership_code == membership_code)
        res = await self.pg_session.execute(stmt)
        family = res.scalars().first()
        if not family:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Family with this membership code does not exist.",
            )

        # Check if already a member
        member_stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family.id,
        )
        if (await self.pg_session.execute(member_stmt)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already a member of this family.",
            )

        # Check if open request exists
        req_stmt = select(FosFamilyJoinRequest).where(
            FosFamilyJoinRequest.user_id == user_id,
            FosFamilyJoinRequest.family_id == family.id,
            FosFamilyJoinRequest.status == "PENDING",
        )
        if (await self.pg_session.execute(req_stmt)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A join request is already pending for this family.",
            )

        req = FosFamilyJoinRequest(
            family_id=family.id,
            user_id=user_id,
            status="PENDING",
        )
        self.pg_session.add(req)
        await self.pg_session.commit()
        await self.pg_session.refresh(req)
        return req

    async def list_join_requests(self, family_id: UUID) -> List[Tuple[FosFamilyJoinRequest, FosProfile]]:
        stmt = (
            select(FosFamilyJoinRequest, FosProfile)
            .join(FosProfile, FosFamilyJoinRequest.user_id == FosProfile.id)
            .where(
                FosFamilyJoinRequest.family_id == family_id,
                FosFamilyJoinRequest.status == "PENDING",
            )
            .order_by(FosFamilyJoinRequest.created_at.desc())
        )
        res = await self.pg_session.execute(stmt)
        return list(res.all())

    async def accept_join_request(self, family_id: UUID, request_id: UUID) -> FosFamilyJoinRequest:
        req_stmt = select(FosFamilyJoinRequest).where(
            FosFamilyJoinRequest.id == request_id,
            FosFamilyJoinRequest.family_id == family_id,
        )
        req = (await self.pg_session.execute(req_stmt)).scalars().first()
        if not req:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request not found.")
        if req.status != "PENDING":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Request is already {req.status}.")

        # Check applicant cap
        current_count, max_memberships = await self.get_user_membership_stats(req.user_id)
        if current_count >= max_memberships:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Applicant has reached their maximum family memberships limit ({current_count}/{max_memberships}). Request remains pending.",
            )

        # Check if already member
        member_stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == req.user_id,
            UserFamilyLink.family_id == family_id,
        )
        if not (await self.pg_session.execute(member_stmt)).scalars().first():
            link = UserFamilyLink(
                user_id=req.user_id,
                family_id=family_id,
                is_family_manager=False,
            )
            self.pg_session.add(link)

        req.status = "ACCEPTED"
        await self.pg_session.commit()
        await self.pg_session.refresh(req)
        return req

    async def decline_join_request(self, family_id: UUID, request_id: UUID) -> FosFamilyJoinRequest:
        req_stmt = select(FosFamilyJoinRequest).where(
            FosFamilyJoinRequest.id == request_id,
            FosFamilyJoinRequest.family_id == family_id,
        )
        req = (await self.pg_session.execute(req_stmt)).scalars().first()
        if not req:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request not found.")
        if req.status != "PENDING":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Request is already {req.status}.")

        req.status = "DECLINED"
        await self.pg_session.commit()
        await self.pg_session.refresh(req)
        return req

    # --- Email Invites ---

    async def create_invite(self, family_id: UUID, invited_by: UUID, email: str) -> FosFamilyInvite:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        invite = FosFamilyInvite(
            family_id=family_id,
            email=email.strip().lower(),
            token=token,
            invited_by=invited_by,
            status="PENDING",
            expires_at=expires_at,
        )
        self.pg_session.add(invite)
        await self.pg_session.commit()
        await self.pg_session.refresh(invite)
        return invite

    async def get_invite_by_token(self, token: str) -> Tuple[FosFamilyInvite, Family, UserBase]:
        stmt = (
            select(FosFamilyInvite, Family, UserBase)
            .join(Family, FosFamilyInvite.family_id == Family.id)
            .join(UserBase, FosFamilyInvite.invited_by == UserBase.id)
            .where(FosFamilyInvite.token == token)
        )
        res = await self.pg_session.execute(stmt)
        row = res.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
        return row

    async def accept_invite(self, token: str, user_id: UUID) -> FosFamilyInvite:
        stmt = select(FosFamilyInvite).where(FosFamilyInvite.token == token)
        invite = (await self.pg_session.execute(stmt)).scalars().first()
        if not invite:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
        if invite.status != "PENDING":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invite is already {invite.status}.")
        if invite.expires_at < datetime.now(timezone.utc):
            invite.status = "EXPIRED"
            await self.pg_session.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite has expired.")

        current_count, max_memberships = await self.get_user_membership_stats(user_id)
        if current_count >= max_memberships:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You have reached your maximum family memberships limit ({current_count}/{max_memberships}).",
            )

        member_stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == invite.family_id,
        )
        if not (await self.pg_session.execute(member_stmt)).scalars().first():
            link = UserFamilyLink(
                user_id=user_id,
                family_id=invite.family_id,
                is_family_manager=False,
            )
            self.pg_session.add(link)

        invite.status = "ACCEPTED"
        await self.pg_session.commit()
        await self.pg_session.refresh(invite)
        return invite
