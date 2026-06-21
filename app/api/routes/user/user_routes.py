import logging

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import AuthServiceDep, UserServiceDep
from app.api.routes.auth.auth_schemas import ChangePasswordRequest, MessageResponse
from app.api.routes.user.user_schemas import (
    RequestEmailChange,
    UserMeResponse,
    UserMeUpdate,
    VerifyEmailChangeOtp,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Get current user details",
)
async def get_current_user_details(current_user: LoggedInUserDep) -> UserMeResponse:
    return UserMeResponse.model_validate(current_user)


@router.put(
    "/me",
    response_model=UserMeResponse,
    summary="Update current user profile",
)
async def update_me(
    req: UserMeUpdate,
    current_user: LoggedInUserDep,
    service: UserServiceDep,
) -> UserMeResponse:
    try:
        user = await service.update_me(current_user, req)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return UserMeResponse.model_validate(user)


@router.post(
    "/me/change-password",
    response_model=MessageResponse,
    summary="Change password for the authenticated user",
)
async def change_password(
    req: ChangePasswordRequest,
    current_user: LoggedInUserDep,
    auth_service: AuthServiceDep,
) -> MessageResponse:
    try:
        await auth_service.change_password(current_user, req)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Password changed successfully")


@router.post(
    "/me/email",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request email change (OTP sent to new address)",
)
async def request_email_change(
    req: RequestEmailChange,
    current_user: LoggedInUserDep,
    auth_service: AuthServiceDep,
) -> MessageResponse:
    try:
        await auth_service.request_email_change(current_user, req.new_email, req.current_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="OTP sent to the new email address")


@router.post(
    "/me/email/verify",
    response_model=MessageResponse,
    summary="Verify OTP and update email",
)
async def verify_email_change(
    req: VerifyEmailChangeOtp,
    current_user: LoggedInUserDep,
    auth_service: AuthServiceDep,
) -> MessageResponse:
    try:
        await auth_service.verify_email_change_otp(current_user, req.new_email, req.otp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Email updated successfully")
