from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.dependencies import InsuranceServiceDep
from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceListResponse,
    InsuranceResponse,
    InsuranceUpdateRequest,
    InstallmentResponse,
)
from app.api.routes.insurance.insurance_service import InsuranceService
from app.api.schemas.pagination import PaginationDep
from app.core.scope import (
    entity_can_edit,
    load_scope_context,
    require_entity_editable,
    require_entity_visible,
)

router = APIRouter(prefix="/families/{family_id}/insurance", tags=["insurance"])


def _resp(ins, is_personal: bool, *, can_edit: bool, summary: dict | None = None, installments=None) -> InsuranceResponse:
    data = ins.model_dump()
    data["is_personal"] = is_personal
    data["can_edit"] = can_edit
    data.update(summary or {})
    if installments is not None:
        data["installments"] = [InstallmentResponse.model_validate(i) for i in installments]
    return InsuranceResponse.model_validate(data)


async def detail(service: InsuranceService, ins, is_personal: bool, *, can_edit: bool) -> InsuranceResponse:
    summary = (await service.installment_summary([ins.id])).get(ins.id)
    return _resp(ins, is_personal, can_edit=can_edit, summary=summary, installments=await service.list_installments(ins))


async def _found(service: InsuranceService, insurance_id: UUID, family_id: UUID):
    found = await service.get_insurance(insurance_id, family_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return found


@router.get("", response_model=InsuranceListResponse)
async def list_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    pagination: PaginationDep,
    family_id: UUID,
) -> InsuranceListResponse:
    ctx = await load_scope_context(insurance_service.pg_session, family_member.id, family_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this family")
    items, total = await insurance_service.list_insurances(family_id, pagination, scope_ctx=ctx)
    summaries = await insurance_service.installment_summary([i.id for i, _ in items])
    return InsuranceListResponse.from_page(
        [
            _resp(i, p, can_edit=entity_can_edit(ctx, i, is_personal=p), summary=summaries.get(i.id))
            for i, p in items
        ],
        total=total,
        pagination=pagination,
    )


@router.post("", response_model=InsuranceResponse, status_code=status.HTTP_201_CREATED)
async def create_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceCreateRequest,
    family_id: UUID,
) -> InsuranceResponse:
    ins, is_personal = await insurance_service.create_insurance(family_id, family_member.id, request)
    return await detail(insurance_service, ins, is_personal, can_edit=True)


@router.get("/{insurance_id}", response_model=InsuranceResponse)
async def get_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    family_id: UUID,
    insurance_id: UUID,
) -> InsuranceResponse:
    ins, is_personal = await _found(insurance_service, insurance_id, family_id)
    try:
        ctx = await require_entity_visible(
            insurance_service.pg_session, family_member.id, family_id, ins, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return await detail(
        insurance_service, ins, is_personal, can_edit=entity_can_edit(ctx, ins, is_personal=is_personal)
    )


@router.patch("/{insurance_id}", response_model=InsuranceResponse)
async def update_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceUpdateRequest,
    family_id: UUID,
    insurance_id: UUID,
) -> InsuranceResponse:
    ins, is_personal = await _found(insurance_service, insurance_id, family_id)
    try:
        ctx = await require_entity_editable(
            insurance_service.pg_session, family_member.id, family_id, ins, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    updated = await insurance_service.update_insurance(
        ins, request, actor_id=family_member.id, is_head=bool(ctx and ctx.is_family_manager)
    )
    return await detail(insurance_service, updated, is_personal, can_edit=True)


@router.delete("/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_insurance(
    family_member: LoggedInFamilyMemberDep,
    insurance_service: InsuranceServiceDep,
    family_id: UUID,
    insurance_id: UUID,
) -> None:
    ins, is_personal = await _found(insurance_service, insurance_id, family_id)
    try:
        await require_entity_editable(
            insurance_service.pg_session, family_member.id, family_id, ins, is_personal=is_personal
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await insurance_service.delete_insurance(ins)
