from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import InsuranceServiceDep
from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceListResponse,
    InsuranceResponse,
    InsuranceUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep
from app.core.scope import load_scope_context, require_entity_editable, require_entity_visible

router = APIRouter(prefix="/families/{family_id}/insurance", tags=["insurance"])


def _resp(ins, is_personal: bool) -> InsuranceResponse:
    data = ins.model_dump()
    data["is_personal"] = is_personal
    return InsuranceResponse.model_validate(data)


@router.get("", response_model=InsuranceListResponse)
async def list_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> InsuranceListResponse:
    scope_ctx = await load_scope_context(
        insurance_service.pg_session, family_member.id, family_id
    )
    items, total = await insurance_service.list_insurances(
        family_id, pagination, scope_ctx=scope_ctx
    )
    return InsuranceListResponse.from_page(
        [_resp(i, p) for i, p in items], total=total, pagination=pagination
    )


@router.post("", response_model=InsuranceResponse, status_code=status.HTTP_201_CREATED)
async def create_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceCreateRequest,
    family_id: UUID,
) -> InsuranceResponse:
    ins, is_personal = await insurance_service.create_insurance(
        family_id, family_member.id, request
    )
    return _resp(ins, is_personal)


@router.get("/{insurance_id}", response_model=InsuranceResponse)
async def get_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    family_id: UUID,
    insurance_id: UUID,
) -> InsuranceResponse:
    found = await insurance_service.get_insurance(insurance_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ins, is_personal = found
    try:
        await require_entity_visible(
            insurance_service.pg_session,
            family_member.id,
            family_id,
            ins,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _resp(ins, is_personal)


@router.patch("/{insurance_id}", response_model=InsuranceResponse)
async def update_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceUpdateRequest,
    family_id: UUID,
    insurance_id: UUID,
) -> InsuranceResponse:
    found = await insurance_service.get_insurance(insurance_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ins, is_personal = found
    try:
        await require_entity_editable(
            insurance_service.pg_session,
            family_member.id,
            family_id,
            ins,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await insurance_service.update_insurance(ins, request)
    return _resp(updated, is_personal)


@router.delete("/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    family_id: UUID,
    insurance_id: UUID,
) -> None:
    found = await insurance_service.get_insurance(insurance_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ins, is_personal = found
    try:
        await require_entity_editable(
            insurance_service.pg_session,
            family_member.id,
            family_id,
            ins,
            is_personal=is_personal,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await insurance_service.delete_insurance(ins)


@router.post("/{insurance_id}/pay-now", response_model=InsuranceResponse)
async def pay_now(
    family_member: LoggedInFamilyMemberDep,
    family_id: UUID,
    insurance_id: UUID,
) -> InsuranceResponse:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Pay now is removed. Insurance premiums apply via the mapped recurring expense.",
    )


@router.post("/{insurance_id}/split-plan", status_code=status.HTTP_410_GONE)
async def upsert_insurance_split_plan(
    family_member: LoggedInFamilyMemberDep,
    family_id: UUID,
    insurance_id: UUID,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Insurance funding splits are removed.",
    )
