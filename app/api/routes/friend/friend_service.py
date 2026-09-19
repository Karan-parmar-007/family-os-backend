from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.friend.friend_schemas import FriendRequestByCode
from app.api.routes.friend.model import Friendship, canonical_user_pair
from app.api.routes.profile.model import FosProfile
from app.api.routes.scheduler.model import Notification
from app.api.routes.user.model import UserFamilyLink
from app.core.constants import NOTIF_STATUS_UNREAD

FRIEND_PENDING = "PENDING"
FRIEND_ACTIVE = "ACTIVE"
FRIEND_REJECTED = "REJECTED"
FRIEND_CANCELLED = "CANCELLED"


class FriendService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def get_friend_code(self, user_id: UUID) -> str:
        profile = await self.pg_session.get(FosProfile, user_id)
        if profile is None:
            raise ValueError("User not found")
        return profile.personal_code

    async def _display_name(self, user_id: UUID) -> str:
        profile = await self.pg_session.get(FosProfile, user_id)
        return profile.display_name if profile is not None else "Someone"

    async def list_friendships(self, user_id: UUID) -> list[tuple[Friendship, FosProfile]]:
        stmt = (
            select(Friendship)
            .where(
                or_(Friendship.user_a_id == user_id, Friendship.user_b_id == user_id),
                Friendship.status.in_([FRIEND_PENDING, FRIEND_ACTIVE]),
            )
            .order_by(Friendship.created_at.desc())
        )
        friendships = list((await self.pg_session.execute(stmt)).scalars().all())
        result: list[tuple[Friendship, FosProfile]] = []
        for friendship in friendships:
            other_id = (
                friendship.user_b_id
                if friendship.user_a_id == user_id
                else friendship.user_a_id
            )
            other = await self.pg_session.get(FosProfile, other_id)
            if other is not None:
                result.append((friendship, other))
        return result

    async def list_active_friends(self, user_id: UUID) -> list[FosProfile]:
        rows = await self.list_friendships(user_id)
        return [other for friendship, other in rows if friendship.status == FRIEND_ACTIVE]

    async def request_by_code(
        self, user_id: UUID, request: FriendRequestByCode
    ) -> Friendship:
        raw = request.friend_code.strip()
        if not (raw.isdigit() and len(raw) == 8):
            raise ValueError("Invalid friend code format")

        stmt = select(FosProfile).where(FosProfile.personal_code == raw)
        target = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if target is None:
            raise ValueError("No user found for this friend code")
        if target.id == user_id:
            raise ValueError("Cannot add yourself as a friend")

        await self._assert_no_active_or_pending_pair(user_id, target.id)

        user_a, user_b = canonical_user_pair(user_id, target.id)
        friendship = Friendship(
            user_a_id=user_a,
            user_b_id=user_b,
            requested_by=user_id,
            status=FRIEND_PENDING,
        )
        self.pg_session.add(friendship)
        await self.pg_session.flush()

        requester_name = await self._display_name(user_id)
        self.pg_session.add(
            Notification(
                user_id=target.id,
                family_id=None,
                type="FRIEND_REQUEST",
                title="Friend request",
                body=f"{requester_name} wants to be friends",
                related_entity_type="FRIENDSHIP",
                related_entity_id=friendship.id,
                allowed_actions={"actions": ["CONFIRM", "REJECT", "DISMISS"]},
                status=NOTIF_STATUS_UNREAD,
            )
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(friendship)
        return friendship

    async def get_friendship(self, friendship_id: UUID) -> Friendship | None:
        return await self.pg_session.get(Friendship, friendship_id)

    async def confirm(
        self, user_id: UUID, friendship: Friendship
    ) -> Friendship:
        if friendship.status != FRIEND_PENDING:
            raise ValueError("Only pending friend requests can be confirmed")
        if user_id not in {friendship.user_a_id, friendship.user_b_id}:
            raise PermissionError("Friendship does not belong to this user")
        if friendship.requested_by == user_id:
            raise PermissionError("You cannot confirm your own friend request")

        friendship.status = FRIEND_ACTIVE
        await self.pg_session.flush()

        other_id = (
            friendship.user_b_id
            if friendship.user_a_id == user_id
            else friendship.user_a_id
        )
        confirmer_name = await self._display_name(user_id)
        self.pg_session.add(
            Notification(
                user_id=other_id,
                family_id=None,
                type="FRIEND_ACCEPTED",
                title="Friend request accepted",
                body=f"{confirmer_name} accepted your friend request",
                related_entity_type="FRIENDSHIP",
                related_entity_id=friendship.id,
                allowed_actions={"actions": ["DISMISS"]},
                status=NOTIF_STATUS_UNREAD,
            )
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(friendship)
        return friendship

    async def reject(self, user_id: UUID, friendship: Friendship) -> Friendship:
        if friendship.status != FRIEND_PENDING:
            raise ValueError("Only pending friend requests can be rejected")
        if user_id not in {friendship.user_a_id, friendship.user_b_id}:
            raise PermissionError("Friendship does not belong to this user")
        if friendship.requested_by == user_id:
            raise PermissionError("You cannot reject your own friend request")

        friendship.status = FRIEND_REJECTED
        await self.pg_session.commit()
        await self.pg_session.refresh(friendship)
        return friendship

    async def cancel(self, user_id: UUID, friendship: Friendship) -> Friendship:
        if friendship.status != FRIEND_PENDING:
            raise ValueError("Only pending friend requests can be cancelled")
        if friendship.requested_by != user_id:
            raise PermissionError("Only the requester can cancel this friend request")

        friendship.status = FRIEND_CANCELLED
        await self.pg_session.commit()
        await self.pg_session.refresh(friendship)
        return friendship

    async def assert_active_friends(self, user_a: UUID, user_b: UUID) -> None:
        if user_a == user_b:
            return
        a, b = canonical_user_pair(user_a, user_b)
        stmt = select(Friendship.id).where(
            Friendship.user_a_id == a,
            Friendship.user_b_id == b,
            Friendship.status == FRIEND_ACTIVE,
        )
        row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError("Users must be active friends for this action")

    async def are_active_friends(self, user_a: UUID, user_b: UUID) -> bool:
        if user_a == user_b:
            return True
        a, b = canonical_user_pair(user_a, user_b)
        stmt = select(Friendship.id).where(
            Friendship.user_a_id == a,
            Friendship.user_b_id == b,
            Friendship.status == FRIEND_ACTIVE,
        )
        row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        return row is not None

    async def share_family(self, user_a: UUID, user_b: UUID, family_id: UUID | None = None) -> bool:
        """True if both users are members of the same family (optionally a specific one)."""
        if user_a == user_b:
            return True
        if family_id is not None:
            stmt = select(UserFamilyLink.user_id).where(
                UserFamilyLink.family_id == family_id,
                UserFamilyLink.user_id.in_([user_a, user_b]),
            )
            members = set((await self.pg_session.execute(stmt)).scalars().all())
            return user_a in members and user_b in members

        stmt_a = select(UserFamilyLink.family_id).where(UserFamilyLink.user_id == user_a)
        families_a = set((await self.pg_session.execute(stmt_a)).scalars().all())
        if not families_a:
            return False
        stmt_b = select(UserFamilyLink.family_id).where(
            UserFamilyLink.user_id == user_b,
            UserFamilyLink.family_id.in_(families_a),
        )
        return (await self.pg_session.execute(stmt_b)).scalar_one_or_none() is not None

    async def can_allocate_to_personal(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        family_id: UUID | None = None,
    ) -> bool:
        if actor_id == target_user_id:
            return True
        if await self.share_family(actor_id, target_user_id, family_id):
            return True
        return await self.are_active_friends(actor_id, target_user_id)

    async def assert_can_allocate_to_personal(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        family_id: UUID | None = None,
    ) -> None:
        ok = await self.can_allocate_to_personal(actor_id, target_user_id, family_id)
        if not ok:
            raise PermissionError(
                "You can only allocate to your own personal savings, "
                "family members, or active friends"
            )

    async def _assert_no_active_or_pending_pair(self, user_a: UUID, user_b: UUID) -> None:
        a, b = canonical_user_pair(user_a, user_b)
        stmt = select(Friendship).where(
            Friendship.user_a_id == a,
            Friendship.user_b_id == b,
            Friendship.status.in_([FRIEND_PENDING, FRIEND_ACTIVE]),
        )
        existing = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("A pending or active friendship already exists")
