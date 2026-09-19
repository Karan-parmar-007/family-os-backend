from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.profile.model import FosProfile
from app.api.routes.family.model import Family
from app.api.routes.user.model import UserFamilyLink, UserBase
from app.api.routes.currency.model import FosCurrency
from app.api.routes.admin.admin_schemas import (
    AdminFamilySummary,
    AdminUserFamilyItem,
    AdminUserSummary,
)
from app.api.routes.currency.currency_schemas import (
    CurrencyCreateRequest,
    CurrencyUpdateRequest,
)

logger = logging.getLogger(__name__)


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ──────── Users ────────
    async def list_users(self) -> list[AdminUserSummary]:
        stmt = select(FosProfile).order_by(FosProfile.created_at.desc())
        profiles = (await self.session.execute(stmt)).scalars().all()

        results: list[AdminUserSummary] = []
        for p in profiles:
            # Query family links for this profile
            link_stmt = (
                select(UserFamilyLink, Family)
                .join(Family, Family.id == UserFamilyLink.family_id)
                .where(UserFamilyLink.user_id == p.id)
            )
            links = (await self.session.execute(link_stmt)).all()

            families_list = [
                AdminUserFamilyItem(
                    id=fam.id,
                    name=fam.name,
                    is_family_manager=link.is_family_manager,
                    joined_at=link.created_at,
                )
                for link, fam in links
            ]

            results.append(
                AdminUserSummary(
                    id=p.id,
                    sso_user_id=p.sso_user_id,
                    email=p.email,
                    display_name=p.display_name,
                    personal_currency=p.personal_currency,
                    timezone=p.timezone,
                    personal_code=p.personal_code,
                    max_family_memberships=p.max_family_memberships,
                    family_count=len(families_list),
                    families=families_list,
                    created_at=p.created_at,
                )
            )
        return results

    async def update_user_cap(self, user_id: UUID, new_cap: int) -> FosProfile | None:
        stmt = select(FosProfile).where(FosProfile.id == user_id)
        profile = (await self.session.execute(stmt)).scalar_one_or_none()
        if profile is None:
            return None
        profile.max_family_memberships = new_cap
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def delete_user(self, user_id: UUID) -> tuple[bool, str]:
        """
        Phase A user deletion policy:
        Blocks deletion with 409 if user is the sole head of any family.
        Otherwise, unlinks memberships, removes personal records, and drops profile.
        """
        # Check if user is sole head of any family
        head_links_stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.is_family_manager == True,
        )
        head_links = (await self.session.execute(head_links_stmt)).scalars().all()
        for hl in head_links:
            # Check how many members are in this family
            member_count_stmt = select(func.count(UserFamilyLink.user_id)).where(
                UserFamilyLink.family_id == hl.family_id
            )
            count = (await self.session.execute(member_count_stmt)).scalar() or 0
            if count <= 1:
                return False, f"Cannot delete user who is the sole manager of family {hl.family_id}. Transfer leadership or delete the family first."

        # Unlink user from all families
        await self.session.execute(
            delete(UserFamilyLink).where(UserFamilyLink.user_id == user_id)
        )

        from app.api.routes.debt.simple_debt_models import FosDebt
        from app.api.routes.money.model import FosMoneyRule, FosMoneyEvent
        from app.api.routes.vault.model import FosVaultItem
        from app.api.routes.family.model import UserGlobalPersonalSavings, SavingsLedger
        from app.api.routes.transfer.model import Transfer
        from app.api.routes.insurance.model import PersonalInsurance
        from app.api.routes.assets.model import PersonalAsset

        await self.session.execute(delete(FosVaultItem).where(FosVaultItem.owner_user_id == user_id))
        await self.session.execute(delete(FosDebt).where(FosDebt.created_by == user_id, FosDebt.scope == "PERSONAL"))
        await self.session.execute(delete(FosMoneyEvent).where(FosMoneyEvent.owner_user_id == user_id))
        await self.session.execute(delete(FosMoneyRule).where(FosMoneyRule.created_by == user_id, FosMoneyRule.scope == "PERSONAL"))
        await self.session.execute(delete(UserGlobalPersonalSavings).where(UserGlobalPersonalSavings.user_id == user_id))
        await self.session.execute(delete(SavingsLedger).where(SavingsLedger.user_id == user_id, SavingsLedger.family_id.is_(None)))
        await self.session.execute(
            delete(Transfer).where(
                (Transfer.from_user_id == user_id) | (Transfer.to_user_id == user_id) | (Transfer.created_by == user_id)
            )
        )
        await self.session.execute(delete(PersonalInsurance).where(PersonalInsurance.user_id == user_id))
        try:
            await self.session.execute(delete(PersonalAsset).where(PersonalAsset.user_id == user_id))
        except Exception:
            logger.exception("personal assets delete skipped")

        # Delete FosProfile
        await self.session.execute(
            delete(FosProfile).where(FosProfile.id == user_id)
        )

        # Delete UserBase if present
        await self.session.execute(
            delete(UserBase).where(UserBase.id == user_id)
        )

        await self.session.commit()
        return True, "User deleted successfully"

    # ──────── Families ────────
    async def list_families(self) -> list[AdminFamilySummary]:
        stmt = select(Family).order_by(Family.created_at.desc())
        families = (await self.session.execute(stmt)).scalars().all()

        results: list[AdminFamilySummary] = []
        for fam in families:
            # Member count
            count_stmt = select(func.count(UserFamilyLink.user_id)).where(
                UserFamilyLink.family_id == fam.id
            )
            member_count = (await self.session.execute(count_stmt)).scalar() or 0

            # Head name
            head_stmt = (
                select(UserBase.name)
                .join(UserFamilyLink, UserFamilyLink.user_id == UserBase.id)
                .where(
                    UserFamilyLink.family_id == fam.id,
                    UserFamilyLink.is_family_manager == True,
                )
            )
            head_name = (await self.session.execute(head_stmt)).scalar_one_or_none()

            results.append(
                AdminFamilySummary(
                    id=fam.id,
                    name=fam.name,
                    currency=fam.currency,
                    timezone=getattr(fam, "timezone", "Asia/Kolkata") or "Asia/Kolkata",
                    member_count=member_count,
                    head_name=head_name,
                    created_at=fam.created_at,
                )
            )
        return results

    async def delete_family(self, family_id: UUID) -> bool:
        """Full cascade delete of a family."""
        stmt = select(Family).where(Family.id == family_id)
        family = (await self.session.execute(stmt)).scalar_one_or_none()
        if family is None:
            return False

        from app.api.routes.debt.simple_debt_models import FosDebt
        from app.api.routes.money.model import FosMoneyRule, FosMoneyEvent
        from app.api.routes.vault.model import FosVaultItem
        from app.api.routes.family.model import (
            FamilyTotalSavings,
            FosFamilyJoinRequest,
            FosFamilyInvite,
            SavingsLedger,
        )
        from app.api.routes.transfer.model import Transfer
        from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
        from app.api.routes.family.model import FamilyRelationship
        from app.api.routes.scheduler.model import ScheduledJob

        await self.session.execute(delete(ScheduledJob).where(ScheduledJob.family_id == family_id))
        await self.session.execute(delete(FosVaultItem).where(FosVaultItem.family_id == family_id))
        await self.session.execute(delete(FosDebt).where(FosDebt.family_id == family_id))
        await self.session.execute(delete(FosMoneyEvent).where(FosMoneyEvent.family_id == family_id))
        await self.session.execute(delete(FosMoneyRule).where(FosMoneyRule.family_id == family_id))
        await self.session.execute(delete(FamilyInsurance).where(FamilyInsurance.family_id == family_id))
        await self.session.execute(delete(PersonalInsurance).where(PersonalInsurance.family_id == family_id))
        await self.session.execute(
            delete(Transfer).where((Transfer.family_id == family_id) | (Transfer.to_family_id == family_id))
        )
        await self.session.execute(
            delete(FamilyRelationship).where(
                (FamilyRelationship.family_a_id == family_id) | (FamilyRelationship.family_b_id == family_id)
            )
        )
        await self.session.execute(delete(FosFamilyJoinRequest).where(FosFamilyJoinRequest.family_id == family_id))
        await self.session.execute(delete(FosFamilyInvite).where(FosFamilyInvite.family_id == family_id))
        await self.session.execute(delete(SavingsLedger).where(SavingsLedger.family_id == family_id))
        await self.session.execute(delete(FamilyTotalSavings).where(FamilyTotalSavings.family_id == family_id))

        # Cascade delete relationships and links
        await self.session.execute(
            delete(UserFamilyLink).where(UserFamilyLink.family_id == family_id)
        )
        await self.session.execute(
            delete(Family).where(Family.id == family_id)
        )
        await self.session.commit()
        return True

    # ──────── Currencies ────────
    async def list_currencies(self) -> list[FosCurrency]:
        stmt = select(FosCurrency).order_by(FosCurrency.code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_currency(self, req: CurrencyCreateRequest) -> FosCurrency:
        code = req.code.upper().strip()
        existing = await self.session.get(FosCurrency, code)
        if existing is not None:
            raise ValueError(f"Currency with code {code} already exists")

        curr = FosCurrency(
            code=code,
            name=req.name.strip(),
            symbol=req.symbol.strip(),
            rate_to_usd=req.rate_to_usd,
            is_active=req.is_active,
        )
        self.session.add(curr)
        await self.session.commit()
        await self.session.refresh(curr)
        return curr

    async def update_currency(self, code: str, req: CurrencyUpdateRequest) -> FosCurrency | None:
        curr = await self.session.get(FosCurrency, code.upper().strip())
        if curr is None:
            return None
        if req.name is not None:
            curr.name = req.name.strip()
        if req.symbol is not None:
            curr.symbol = req.symbol.strip()
        if req.rate_to_usd is not None:
            curr.rate_to_usd = req.rate_to_usd
        if req.is_active is not None:
            curr.is_active = req.is_active
        await self.session.commit()
        await self.session.refresh(curr)
        return curr

    async def delete_currency(self, code: str) -> tuple[bool, str]:
        code = code.upper().strip()
        if code == "USD":
            return False, "Cannot delete canonical base currency USD"

        # Check if used by any profile
        stmt_prof = select(func.count(FosProfile.id)).where(FosProfile.personal_currency == code)
        count_prof = (await self.session.execute(stmt_prof)).scalar() or 0
        if count_prof > 0:
            return False, f"Currency {code} is in use by {count_prof} user profiles and cannot be deleted"

        # Check if used by any family
        stmt_fam = select(func.count(Family.id)).where(Family.currency == code)
        count_fam = (await self.session.execute(stmt_fam)).scalar() or 0
        if count_fam > 0:
            return False, f"Currency {code} is in use by {count_fam} families and cannot be deleted"

        curr = await self.session.get(FosCurrency, code)
        if curr is None:
            return False, "Currency not found"

        await self.session.delete(curr)
        await self.session.commit()
        return True, "Currency deleted successfully"
