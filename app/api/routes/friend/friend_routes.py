from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import FriendServiceDep
from app.api.routes.friend.friend_schemas import (
    FriendCodeResponse,
    FriendRequestByCode,
    FriendshipListResponse,
    FriendshipResponse,
    FriendUserListResponse,
    FriendUserOption,
)
from app.api.routes.friend.friend_service import FRIEND_ACTIVE

router = APIRouter(prefix="/friends", tags=["friends"])


def _direction(user_id: UUID, friendship, other_name: str) -> FriendshipResponse:
    other_id = (
        friendship.user_b_id if friendship.user_a_id == user_id else friendship.user_a_id
    )
    if friendship.status == FRIEND_ACTIVE:
        direction = "ACTIVE"
    elif friendship.requested_by == user_id:
        direction = "OUTGOING"
    else:
        direction = "INCOMING"
    return FriendshipResponse(
        id=friendship.id,
        user_a_id=friendship.user_a_id,
        user_b_id=friendship.user_b_id,
        requested_by=friendship.requested_by,
        status=friendship.status,
        created_at=friendship.created_at,
        other_user_id=other_id,
        other_user_name=other_name,
        direction=direction,
    )


@router.get("/me/code", response_model=FriendCodeResponse)
async def get_my_friend_code(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
) -> FriendCodeResponse:
    code = await friend_service.get_friend_code(user.id)
    return FriendCodeResponse(friend_code=code)


@router.get("", response_model=FriendshipListResponse)
async def list_friends(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
) -> FriendshipListResponse:
    rows = await friend_service.list_friendships(user.id)
    return FriendshipListResponse(
        items=[_direction(user.id, f, other.display_name) for f, other in rows]
    )


@router.get("/active", response_model=FriendUserListResponse)
async def list_active_friends(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
) -> FriendUserListResponse:
    friends = await friend_service.list_active_friends(user.id)
    return FriendUserListResponse(
        items=[FriendUserOption(id=f.id, name=f.display_name) for f in friends]
    )


@router.post("/request", response_model=FriendshipResponse, status_code=status.HTTP_201_CREATED)
async def request_friend(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
    body: FriendRequestByCode,
) -> FriendshipResponse:
    try:
        friendship = await friend_service.request_by_code(user.id, body)
        other_id = (
            friendship.user_b_id
            if friendship.user_a_id == user.id
            else friendship.user_a_id
        )
        from app.api.routes.profile.model import FosProfile

        other = await friend_service.pg_session.get(FosProfile, other_id)
        return _direction(user.id, friendship, other.display_name if other else "User")
    except ValueError as exc:
        await friend_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{friendship_id}/confirm", response_model=FriendshipResponse)
async def confirm_friend(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
    friendship_id: UUID,
) -> FriendshipResponse:
    friendship = await friend_service.get_friendship(friendship_id)
    if friendship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        updated = await friend_service.confirm(user.id, friendship)
        other_id = (
            updated.user_b_id if updated.user_a_id == user.id else updated.user_a_id
        )
        from app.api.routes.profile.model import FosProfile

        other = await friend_service.pg_session.get(FosProfile, other_id)
        return _direction(user.id, updated, other.display_name if other else "User")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await friend_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{friendship_id}/reject", response_model=FriendshipResponse)
async def reject_friend(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
    friendship_id: UUID,
) -> FriendshipResponse:
    friendship = await friend_service.get_friendship(friendship_id)
    if friendship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        updated = await friend_service.reject(user.id, friendship)
        other_id = (
            updated.user_b_id if updated.user_a_id == user.id else updated.user_a_id
        )
        from app.api.routes.profile.model import FosProfile

        other = await friend_service.pg_session.get(FosProfile, other_id)
        return _direction(user.id, updated, other.display_name if other else "User")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await friend_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{friendship_id}/cancel", response_model=FriendshipResponse)
async def cancel_friend(
    user: LoggedInUserDep,
    friend_service: FriendServiceDep,
    friendship_id: UUID,
) -> FriendshipResponse:
    friendship = await friend_service.get_friendship(friendship_id)
    if friendship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        updated = await friend_service.cancel(user.id, friendship)
        other_id = (
            updated.user_b_id if updated.user_a_id == user.id else updated.user_a_id
        )
        from app.api.routes.profile.model import FosProfile

        other = await friend_service.pg_session.get(FosProfile, other_id)
        return _direction(user.id, updated, other.display_name if other else "User")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await friend_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
