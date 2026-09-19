from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.friend.friend_service import FriendService
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.funding import FundingSourceInput
from app.core.constants import POOL_FAMILY, POOL_PERSONAL
from app.core.savings_ledger_service import SavingsPoolRef


async def assert_user_can_fund_from(
    session: AsyncSession,
    user_id: UUID,
    source: FundingSourceInput,
    *,
    primary_family_id: UUID | None = None,
) -> None:
    if source.pool_type == POOL_PERSONAL:
        if source.user_id is None:
            raise ValueError("user_id is required for PERSONAL funding sources")
        friend_service = FriendService(session)
        await friend_service.assert_can_allocate_to_personal(
            user_id, source.user_id, primary_family_id
        )
        return

    stmt = select(UserFamilyLink.user_id).where(
        UserFamilyLink.user_id == user_id,
        UserFamilyLink.family_id == source.family_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise PermissionError("You can only use FAMILY pools where you are a member")


def validate_funding_source_total(
    total_amount: Decimal,
    funding_sources: list[FundingSourceInput],
) -> None:
    if not funding_sources:
        raise ValueError("funding_sources cannot be empty")
    split_total = sum((source.amount for source in funding_sources), Decimal("0"))
    if split_total != total_amount:
        raise ValueError(
            f"funding_sources total ({split_total}) must equal amount ({total_amount})"
        )


def validate_family_personal_log_split(
    total_amount: Decimal,
    family_amount: Decimal | None,
    personal_amount: Decimal | None,
) -> None:
    """Reject pseudo-splits where only one side is set or either equals the total."""
    if family_amount is None and personal_amount is None:
        return

    if family_amount is None or personal_amount is None:
        raise ValueError(
            "When splitting, both family and personal amounts must be greater than zero."
        )

    family = family_amount
    personal = personal_amount

    if family == total_amount or personal == total_amount:
        raise ValueError(
            "Family and personal amounts must each be less than the total when splitting."
        )
    if family <= 0 or personal <= 0:
        raise ValueError(
            "When splitting, both family and personal amounts must be greater than zero."
        )
    if family + personal != total_amount:
        raise ValueError(
            f"family_amount ({family}) + personal_savings_amount ({personal}) "
            f"must equal total_amount ({total_amount})"
        )


def validate_log_funding_sources(
    total_amount: Decimal,
    funding_sources: list[FundingSourceInput],
    primary_family_id: UUID,
) -> None:
    """Validate funding allocations; allow multi-PERSONAL and other-family rows."""
    validate_funding_source_total(total_amount, funding_sources)

    personal_total = sum(
        (source.amount for source in funding_sources if source.pool_type == POOL_PERSONAL),
        Decimal("0"),
    )
    primary_family_total = sum(
        (
            source.amount
            for source in funding_sources
            if source.pool_type == POOL_FAMILY and source.family_id == primary_family_id
        ),
        Decimal("0"),
    )
    other_family_total = sum(
        (
            source.amount
            for source in funding_sources
            if source.pool_type == POOL_FAMILY
            and source.family_id is not None
            and source.family_id != primary_family_id
        ),
        Decimal("0"),
    )
    personal_user_ids = {
        source.user_id
        for source in funding_sources
        if source.pool_type == POOL_PERSONAL and source.user_id is not None
    }

    # Simple family + single personal: both sides must be partial.
    if (
        other_family_total == 0
        and len(personal_user_ids) <= 1
        and (primary_family_total > 0 or personal_total > 0)
        and len(funding_sources) <= 2
    ):
        if personal_total <= 0 or primary_family_total <= 0:
            raise ValueError(
                "When splitting, both family and personal amounts must be greater than zero."
            )
        if primary_family_total == total_amount or personal_total == total_amount:
            raise ValueError(
                "Family and personal amounts must each be less than the total when splitting."
            )


def pool_ref_from_funding_source(
    user_id: UUID,
    source: FundingSourceInput,
) -> SavingsPoolRef:
    if source.pool_type == POOL_FAMILY:
        return SavingsPoolRef(pool_type=POOL_FAMILY, family_id=source.family_id)
    target = source.user_id or user_id
    return SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=target)


def summarize_personal_funding(
    funding_sources: list[FundingSourceInput] | None,
    *,
    actor_user_id: UUID | None = None,
) -> tuple[Decimal, UUID | None]:
    """Return (personal_total, denormalized personal_savings_user_id)."""
    if not funding_sources:
        return Decimal("0"), None
    personal_sources = [s for s in funding_sources if s.pool_type == POOL_PERSONAL]
    if not personal_sources:
        return Decimal("0"), None
    total = sum((s.amount for s in personal_sources), Decimal("0"))
    if actor_user_id is not None:
        for s in personal_sources:
            if s.user_id == actor_user_id:
                return total, actor_user_id
    return total, personal_sources[0].user_id
