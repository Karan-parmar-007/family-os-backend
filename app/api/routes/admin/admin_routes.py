import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, UploadFile, File, status

from app.api.db_dependencies import PGSessionDep, GarageClientDep
from app.auth.dependencies import AdminDep
from app.api.routes.admin.admin_schemas import (
    AdminFamilyListResponse,
    AdminUserListResponse,
    AdminUserSummary,
    AdminUserUpdateCapRequest,
)
from app.api.routes.currency.currency_schemas import (
    CurrencyCreateRequest,
    CurrencyUpdateRequest,
    FosCurrencyListResponse,
    FosCurrencyResponse,
)
from app.api.routes.admin.admin_service import AdminService
from app.api.routes.currency.model import FosCurrency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ──────────────── Currencies ────────────────
@router.get("/currencies", response_model=FosCurrencyListResponse, summary="List all currencies (admin)")
async def admin_list_currencies(
    admin: AdminDep,
    session: PGSessionDep,
) -> FosCurrencyListResponse:
    service = AdminService(session)
    items = await service.list_currencies()
    return FosCurrencyListResponse(
        items=[FosCurrencyResponse.model_validate(c) for c in items]
    )


@router.post("/currencies", response_model=FosCurrencyResponse, status_code=status.HTTP_201_CREATED, summary="Create new currency")
async def admin_create_currency(
    req: CurrencyCreateRequest,
    admin: AdminDep,
    session: PGSessionDep,
) -> FosCurrencyResponse:
    service = AdminService(session)
    try:
        curr = await service.create_currency(req)
        return FosCurrencyResponse.model_validate(curr)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/currencies/{code}", response_model=FosCurrencyResponse, summary="Update currency")
async def admin_update_currency(
    code: str,
    req: CurrencyUpdateRequest,
    admin: AdminDep,
    session: PGSessionDep,
) -> FosCurrencyResponse:
    service = AdminService(session)
    curr = await service.update_currency(code, req)
    if curr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Currency not found")
    return FosCurrencyResponse.model_validate(curr)


@router.delete("/currencies/{code}", summary="Delete currency")
async def admin_delete_currency(
    code: str,
    admin: AdminDep,
    session: PGSessionDep,
):
    service = AdminService(session)
    ok, msg = await service.delete_currency(code)
    if not ok:
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
    return {"message": msg}


@router.post("/currencies/{code}/logo", summary="Upload currency logo")
async def admin_upload_currency_logo(
    code: str,
    file: UploadFile = File(...),
    admin: AdminDep = None,
    session: PGSessionDep = None,
    garage_client: GarageClientDep = None,
):
    code = code.upper().strip()
    curr = await session.get(FosCurrency, code)
    if curr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Currency not found")

    content = await file.read()
    key = f"familyos/currencies/{code.lower()}.png"
    try:
        from app.config import garage_settings
        bucket = garage_settings.GARAGE_BUCKET
        await garage_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=file.content_type or "image/png",
        )
        curr.logo_key = key
        await session.commit()
        return {"message": "Logo uploaded", "logoKey": key}
    except Exception as exc:
        logger.exception("Garage logo upload failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload logo to storage")


# ──────────────── Users ────────────────
@router.get("/users", response_model=AdminUserListResponse, summary="List all users for platform admin")
async def admin_list_users(
    admin: AdminDep,
    session: PGSessionDep,
) -> AdminUserListResponse:
    service = AdminService(session)
    users = await service.list_users()
    return AdminUserListResponse(items=users)


@router.patch("/users/{user_id}", response_model=dict, summary="Update user max_family_memberships")
async def admin_update_user_cap(
    user_id: UUID,
    req: AdminUserUpdateCapRequest,
    admin: AdminDep,
    session: PGSessionDep,
):
    service = AdminService(session)
    profile = await service.update_user_cap(user_id, req.max_family_memberships)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "message": "User cap updated successfully",
        "userId": str(profile.id),
        "maxFamilyMemberships": profile.max_family_memberships,
    }


@router.delete("/users/{user_id}", summary="Delete user Family OS profile (Phase A)")
async def admin_delete_user(
    user_id: UUID,
    admin: AdminDep,
    session: PGSessionDep,
):
    service = AdminService(session)
    ok, msg = await service.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
    return {"message": msg}


# ──────────────── Families ────────────────
@router.get("/families", response_model=AdminFamilyListResponse, summary="List all families (admin)")
async def admin_list_families(
    admin: AdminDep,
    session: PGSessionDep,
) -> AdminFamilyListResponse:
    service = AdminService(session)
    families = await service.list_families()
    return AdminFamilyListResponse(items=families)


@router.delete("/families/{family_id}", summary="Delete family cascade")
async def admin_delete_family(
    family_id: UUID,
    admin: AdminDep,
    session: PGSessionDep,
):
    service = AdminService(session)
    ok = await service.delete_family(family_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Family not found")
    return {"message": "Family and associated records deleted successfully"}
