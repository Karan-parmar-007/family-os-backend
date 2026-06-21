import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.auth_cookies import clear_auth_cookies, set_auth_cookies
from app.api.dependencies import AuthServiceDep, CurrentUserDep
from app.api.routes.auth.auth_schemas import (
    AccountSetupRequest,
    ForgetPasswordRequest,
    InviteMemberRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    VerifyEmailRequest,
)
from app.api.routes.user.model import UserFamilyLink

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Sign up a new user",
)
async def signup(
    req: SignupRequest,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    try:
        access_token, refresh_token, csrf_token = await service.signup(req.email, req.password, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    set_auth_cookies(response, access_token, refresh_token, csrf_token=csrf_token)
    return MessageResponse(message="Signup successful")


@router.post(
    "/login",
    response_model=MessageResponse,
    summary="Login with email and password",
)
async def login(
    req: LoginRequest,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    try:
        access_token, refresh_token, csrf_token = await service.login(req.email, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    set_auth_cookies(response, access_token, refresh_token, csrf_token=csrf_token)
    return MessageResponse(message="Login successful")


@router.post(
    "/refresh",
    response_model=MessageResponse,
    summary="Refresh access token",
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    try:
        access_token, new_refresh_token, csrf_token = await service.refresh_token(refresh_token)
    except ValueError as exc:
        clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    set_auth_cookies(response, access_token, new_refresh_token, csrf_token=csrf_token)
    return MessageResponse(message="Token refreshed")


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout (revoke refresh token and clear cookies)",
)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await service.logout(refresh_token)

    clear_auth_cookies(response)
    return MessageResponse(message="Logged out")


@router.post(
    "/forget-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send password reset email",
)
async def forget_password(req: ForgetPasswordRequest, service: AuthServiceDep) -> MessageResponse:
    await service.forget_password(req.email)
    return MessageResponse(message="If the email exists, a reset link has been sent")


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password using token",
)
async def reset_password(req: ResetPasswordRequest, service: AuthServiceDep) -> MessageResponse:
    try:
        await service.reset_password(req.token, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Password reset successful")


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email using token",
)
async def verify_email(req: VerifyEmailRequest, service: AuthServiceDep) -> MessageResponse:
    try:
        await service.verify_email(req.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Email verified successfully")


@router.post(
    "/invite-member",
    response_model=MessageResponse,
    summary="Invite a user to a family (manager only)",
)
async def invite_member(
    req: InviteMemberRequest,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
) -> MessageResponse:
    # Verify the current user is a manager of the requested family
    stmt = select(UserFamilyLink).where(
        UserFamilyLink.user_id == current_user.id,
        UserFamilyLink.family_id == req.family_id,
        UserFamilyLink.is_family_manager.is_(True),
    )
    result = await service.pg_session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only family managers can invite members",
        )

    try:
        await service.invite_member(
            inviter_id=current_user.id,
            family_id=req.family_id,
            email=req.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return MessageResponse(message="Invitation sent successfully")


@router.post(
    "/complete-account-setup",
    response_model=MessageResponse,
    summary="Complete account setup via invite link",
)
async def complete_account_setup(
    req: AccountSetupRequest,
    service: AuthServiceDep,
) -> MessageResponse:
    """
    Finalises a new user's account created via family invite.
    Returns 200; frontend must redirect the user to the login page.
    """
    try:
        await service.complete_account_setup(
            email=req.email,
            token=req.token,
            name=req.name,
            password=req.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return MessageResponse(message="Account setup successful. Please log in.")


