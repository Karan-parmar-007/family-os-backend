# app/api/routes/profile/profile_routes.py
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.db_dependencies import PGSessionDep
from app.api.dependencies import FamilyServiceDep
from app.api.routes.family.savings_schemas import (
    GlobalSavingsResponse,
    SavingsLedgerEntryResponse,
)
from app.api.routes.profile.profile_schemas import (
    ALLOWED_TIMEZONES,
    ProfileResponse,
    ProfileSetupRequest,
    ProfileUpdateRequest,
)
from app.api.routes.profile.profile_service import ProfileService
from app.api.schemas.pagination import PaginatedResponse, PaginationDep
from app.auth.dependencies import AuthenticatedDep
from app.auth.fos_profile import FosProfileDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


@router.get(
    "",
    response_model=ProfileResponse,
    summary="Get my Family OS profile",
)
async def get_me(
    identity: AuthenticatedDep,
    session: PGSessionDep,
) -> ProfileResponse:
    service = ProfileService(session)
    profile = await service.get_by_sso_id(identity.user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Complete /me/setup first.",
        )
    return ProfileResponse.model_validate(profile)


@router.post(
    "/setup",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="One-time Family OS profile setup (first login)",
)
async def setup_profile(
    req: ProfileSetupRequest,
    identity: AuthenticatedDep,
    session: PGSessionDep,
) -> ProfileResponse:
    errors: dict[str, str] = {}

    # Validate all fields before bailing — no early escape
    if not req.display_name:
        errors["displayName"] = "Display name is required"
    if req.currency_code not in {"USD", "INR", "EUR", "GBP", "AED", "SGD",
                                  "JPY", "AUD", "CAD", "CHF", "HKD", "NZD"}:
        errors["currencyCode"] = f"Unsupported currency: {req.currency_code}"
    if req.timezone not in ALLOWED_TIMEZONES:
        errors["timezone"] = f"Unsupported timezone: {req.timezone}"

    try:
        origin = Decimal(req.personal_savings_origin or "0")
        if origin < 0:
            errors["personalSavingsOrigin"] = "Savings origin must be >= 0"
    except Exception:
        errors["personalSavingsOrigin"] = "Savings origin must be a valid number"

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    service = ProfileService(session)
    try:
        profile = await service.create_profile(
            sso_user_id=identity.user_id,
            email=identity.email,
            req=req,
        )
    except ValueError as exc:
        if str(exc) == "profile_exists":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Profile already exists. Use PATCH /me to update.",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    from app.core.constants import POOL_PERSONAL
    from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef

    origin = Decimal(req.personal_savings_origin or "0")
    try:
        await SavingsLedgerService(session).set_origin(
            SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=profile.id),
            origin,
        )
        await session.commit()
        await session.refresh(profile)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile already exists (concurrent request).",
        )

    return ProfileResponse.model_validate(profile)


@router.patch(
    "",
    response_model=ProfileResponse,
    summary="Update my Family OS profile (name, currency, timezone)",
)
async def update_me(
    req: ProfileUpdateRequest,
    identity: AuthenticatedDep,
    session: PGSessionDep,
) -> ProfileResponse:
    errors: dict[str, str] = {}

    if req.currency_code is not None and req.currency_code not in {
        "USD", "INR", "EUR", "GBP", "AED", "SGD",
        "JPY", "AUD", "CAD", "CHF", "HKD", "NZD",
    }:
        errors["currencyCode"] = f"Unsupported currency: {req.currency_code}"
    if req.timezone is not None and req.timezone not in ALLOWED_TIMEZONES:
        errors["timezone"] = f"Unsupported timezone: {req.timezone}"

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    service = ProfileService(session)
    profile = await service.get_by_sso_id(identity.user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Complete /me/setup first.",
        )

    updated = await service.update_profile(profile, req)
    return ProfileResponse.model_validate(updated)


@router.get(
    "/savings",
    response_model=GlobalSavingsResponse,
    summary="Personal savings pool (read-only)",
)
async def get_personal_savings(
    profile: FosProfileDep,
    family_service: FamilyServiceDep,
) -> GlobalSavingsResponse:
    entry = await family_service.get_personal_savings(profile.id)
    return GlobalSavingsResponse(
        user_id=profile.id,
        origin_amount=entry.origin_amount if entry else 0,
        total_savings=entry.total_savings if entry else 0,
    )


@router.get(
    "/savings/ledger",
    response_model=PaginatedResponse[SavingsLedgerEntryResponse],
    summary="Personal savings ledger (read-only)",
)
async def list_personal_savings_ledger(
    profile: FosProfileDep,
    family_service: FamilyServiceDep,
    pagination: PaginationDep,
) -> PaginatedResponse[SavingsLedgerEntryResponse]:
    items, total = await family_service.list_personal_savings_ledger(profile.id, pagination)
    return PaginatedResponse.from_page(
        [SavingsLedgerEntryResponse.model_validate(i) for i in items],
        total=total,
        pagination=pagination,
    )
