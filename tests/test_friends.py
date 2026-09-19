"""Friends service unit tests."""

from uuid import uuid4

import pytest

from app.api.routes.friend.friend_schemas import FriendRequestByCode
from app.api.routes.friend.friend_service import FRIEND_ACTIVE, FRIEND_PENDING, FriendService
from app.api.routes.friend.model import canonical_user_pair
from app.api.routes.user.model import UserBase


def test_canonical_user_pair_orders_consistently():
    a = uuid4()
    b = uuid4()
    assert canonical_user_pair(a, b) == canonical_user_pair(b, a)


@pytest.mark.integration
async def test_friend_request_confirm_flow(db_session):
    suffix = uuid4().hex[:8]
    alice = UserBase(
        email=f"alice-{suffix}@example.com",
        name="Alice",
        password="x",
        friend_code=f"{int(suffix[:8], 16) % 100000000:08d}"[:8].zfill(8),
    )
    bob_code = f"{(int(suffix[:8], 16) + 1) % 100000000:08d}"
    bob = UserBase(
        email=f"bob-{suffix}@example.com",
        name="Bob",
        password="x",
        friend_code=bob_code,
    )
    # Ensure unique codes
    alice.friend_code = f"1{int(suffix[:7], 16) % 10000000:07d}"
    bob.friend_code = f"2{int(suffix[:7], 16) % 10000000:07d}"
    db_session.add_all([alice, bob])
    await db_session.commit()

    service = FriendService(db_session)
    friendship = await service.request_by_code(
        alice.id, FriendRequestByCode(friend_code=bob.friend_code)
    )
    assert friendship.status == FRIEND_PENDING

    confirmed = await service.confirm(bob.id, friendship)
    assert confirmed.status == FRIEND_ACTIVE
    await service.assert_active_friends(alice.id, bob.id)

    assert await service.can_allocate_to_personal(alice.id, bob.id) is True
