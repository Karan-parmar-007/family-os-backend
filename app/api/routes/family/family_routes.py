import logging
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUserDep, FamilyServiceDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep, LoggedInFamilyManagerDep
from app.api.routes.family.family_schemas import (
    FamilyCreateRequest,
    FamilyCreateResponse,
    FamilyListResponse,
    FamilySummaryResponse,
    FamilyMemberResponse,
    FamilyMemberListResponse,
    FamilyTotalSavingsResponse,
    FamilyUpdateRequest,
    FamilyUpdateResponse,
    FamilyJoinRequestCreate,
    FamilyJoinRequestListResponse,
    FamilyJoinRequestItemResponse,
    FamilyJoinRequestActionResponse,
    FamilyInviteCreateRequest,
    FamilyInviteResponse,
    FamilyInviteDetailResponse,
)
from app.api.routes.family.savings_schemas import (
    SavingsLedgerEntryResponse,
)
from app.api.schemas.pagination import PaginatedResponse, PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families", tags=["families"])


@router.get(
    "",
    response_model=FamilyListResponse,
    summary="List families for the current user",
)
async def list_families(
    family_service: FamilyServiceDep,
    current_user: CurrentUserDep,
) -> FamilyListResponse:
    """Return every family the authenticated user belongs to with cap metrics."""
    rows = await family_service.list_user_families(current_user.id)
    count, max_cap = await family_service.get_user_membership_stats(current_user.id)
    return FamilyListResponse(
        items=[
            FamilySummaryResponse(
                id=family.id,
                name=family.name,
                currency=family.currency,
                timezone=family.timezone,
                is_manager=link.is_family_manager,
                membership_code=family.membership_code,
                link_code=family.link_code,
                created_at=family.created_at,
            )
            for family, link in rows
        ],
        membership_count=count,
        max_family_memberships=max_cap,
    )


@router.post(
    "",
    response_model=FamilyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new family",
)
async def create_family(
    request: FamilyCreateRequest,
    family_service: FamilyServiceDep,
    current_user: CurrentUserDep,
) -> FamilyCreateResponse:
    """Create a family and automatically link creator as head with initial origin pool."""
    new_family = await family_service.create_family(
        user_id=current_user.id,
        family_name=request.name,
        currency=request.currency,
        timezone_str=request.timezone,
        origin_amount=request.origin_amount,
    )
    return FamilyCreateResponse(
        message="Family created successfully",
        id=new_family.id,
        name=new_family.name,
        currency=new_family.currency,
        timezone=new_family.timezone,
        membership_code=new_family.membership_code,
        link_code=new_family.link_code,
    )


@router.put(
    "/{family_id}",
    response_model=FamilyUpdateResponse,
    summary="Update family details",
)
async def update_family(
    family_id: UUID,
    request: FamilyUpdateRequest,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyManagerDep,
) -> FamilyUpdateResponse:
    updated = await family_service.update_family(
        family_id=family_id,
        name=request.name,
        currency=request.currency,
        timezone_str=request.timezone,
    )
    return FamilyUpdateResponse(
        id=updated.id,
        name=updated.name,
        currency=updated.currency,
        timezone=updated.timezone,
    )


@router.get(
    "/{family_id}/members",
    response_model=FamilyMemberListResponse,
    summary="Get all members of a family",
)
async def get_family_members(
    family_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyMemberDep,
) -> FamilyMemberListResponse:
    members = await family_service.get_family_members(family_id)
    return FamilyMemberListResponse(
        items=[
            FamilyMemberResponse(
                id=profile.id,
                email=profile.email,
                name=profile.display_name,
                is_family_manager=link.is_family_manager,
                joined_at=link.created_at,
            )
            for profile, link in members
        ]
    )


@router.get(
    "/{family_id}/total-savings",
    response_model=FamilyTotalSavingsResponse,
    summary="Get family total savings",
)
async def get_family_total_savings(
    family_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyMemberDep,
) -> FamilyTotalSavingsResponse:
    entry = await family_service.get_family_total_savings(family_id)
    return FamilyTotalSavingsResponse(
        family_id=family_id,
        total_savings=float(entry.total_savings) if entry else 0.0,
    )


@router.get(
    "/{family_id}/savings/ledger",
    response_model=PaginatedResponse[SavingsLedgerEntryResponse],
    summary="List family savings ledger entries (read-only)",
)
async def list_family_savings_ledger(
    family_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyMemberDep,
    pagination: PaginationDep,
) -> PaginatedResponse[SavingsLedgerEntryResponse]:
    items, total = await family_service.list_family_savings_ledger(family_id, pagination)
    return PaginatedResponse.from_page(
        [SavingsLedgerEntryResponse.model_validate(i) for i in items],
        total=total,
        pagination=pagination,
    )


# -----------------------------------------------
# Join Requests (by 8-digit membership_code)
# -----------------------------------------------

@router.post(
    "/join-request",
    response_model=FamilyJoinRequestActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a request to join a family by membership code",
)
async def submit_join_request(
    request: FamilyJoinRequestCreate,
    family_service: FamilyServiceDep,
    current_user: CurrentUserDep,
) -> FamilyJoinRequestActionResponse:
    req = await family_service.create_join_request(current_user.id, request.membership_code)
    return FamilyJoinRequestActionResponse(
        message="Join request submitted successfully. Awaiting family head approval.",
        id=req.id,
        status=req.status,
    )


@router.get(
    "/{family_id}/join-requests",
    response_model=FamilyJoinRequestListResponse,
    summary="List pending join requests for a family (Head only)",
)
async def list_join_requests(
    family_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyManagerDep,
) -> FamilyJoinRequestListResponse:
    rows = await family_service.list_join_requests(family_id)
    return FamilyJoinRequestListResponse(
        items=[
            FamilyJoinRequestItemResponse(
                id=req.id,
                family_id=req.family_id,
                user_id=req.user_id,
                user_name=profile.display_name,
                user_email=profile.email,
                status=req.status,
                created_at=req.created_at,
            )
            for req, profile in rows
        ]
    )


@router.post(
    "/{family_id}/join-requests/{request_id}/accept",
    response_model=FamilyJoinRequestActionResponse,
    summary="Accept a join request (Head only)",
)
async def accept_join_request(
    family_id: UUID,
    request_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyManagerDep,
) -> FamilyJoinRequestActionResponse:
    req = await family_service.accept_join_request(family_id, request_id)
    return FamilyJoinRequestActionResponse(
        message="Join request accepted. User is now a family member.",
        id=req.id,
        status=req.status,
    )


@router.post(
    "/{family_id}/join-requests/{request_id}/decline",
    response_model=FamilyJoinRequestActionResponse,
    summary="Decline a join request (Head only)",
)
async def decline_join_request(
    family_id: UUID,
    request_id: UUID,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyManagerDep,
) -> FamilyJoinRequestActionResponse:
    req = await family_service.decline_join_request(family_id, request_id)
    return FamilyJoinRequestActionResponse(
        message="Join request declined.",
        id=req.id,
        status=req.status,
    )


# -----------------------------------------------
# Email Invites
# -----------------------------------------------

@router.post(
    "/{family_id}/invites",
    response_model=FamilyInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new member via email (Head only)",
)
async def create_invite(
    family_id: UUID,
    request: FamilyInviteCreateRequest,
    family_service: FamilyServiceDep,
    current_user: LoggedInFamilyManagerDep,
) -> FamilyInviteResponse:
    inv = await family_service.create_invite(family_id, current_user.id, request.email)
    return FamilyInviteResponse(
        id=inv.id,
        family_id=inv.family_id,
        email=inv.email,
        token=inv.token,
        status=inv.status,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


@router.get(
    "/invites/{token}",
    response_model=FamilyInviteDetailResponse,
    summary="Get invite details by token",
)
async def get_invite_detail(
    token: str,
    family_service: FamilyServiceDep,
) -> FamilyInviteDetailResponse:
    inv, fam, inviter = await family_service.get_invite_by_token(token)
    return FamilyInviteDetailResponse(
        id=inv.id,
        family_name=fam.name,
        invited_by_email=inviter.email,
        email=inv.email,
        status=inv.status,
        expires_at=inv.expires_at,
    )


@router.post(
    "/invites/{token}/accept",
    response_model=FamilyJoinRequestActionResponse,
    summary="Accept an invite to join a family",
)
async def accept_invite(
    token: str,
    family_service: FamilyServiceDep,
    current_user: CurrentUserDep,
) -> FamilyJoinRequestActionResponse:
    inv = await family_service.accept_invite(token, current_user.id)
    return FamilyJoinRequestActionResponse(
        message="Invite accepted successfully. You are now a family member.",
        id=inv.id,
        status=inv.status,
    )
