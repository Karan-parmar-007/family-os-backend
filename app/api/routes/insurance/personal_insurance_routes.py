from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import InsuranceServiceDep
from app.api.routes.insurance.insurance_routes import _resp, detail
from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceListResponse,
    InsuranceResponse,
    InsuranceUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/personal/insurance", tags=["personal-insurance"])


async def _own(insurance_service, insurance_id: UUID, user_id: UUID):
    ins = await insurance_service.get_personal_insurance(insurance_id, user_id)
    if ins is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return ins


@router.get("", response_model=InsuranceListResponse)
async def list_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    pagination: PaginationDep,
) -> InsuranceListResponse:
    items, total = await insurance_service.list_personal_insurances(user.id, pagination)
    summaries = await insurance_service.installment_summary([i.id for i in items])
    return InsuranceListResponse.from_page(
        [_resp(i, True, can_edit=True, summary=summaries.get(i.id)) for i in items],
        total=total,
        pagination=pagination,
    )


@router.post("", response_model=InsuranceResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceCreateRequest,
    family_id: UUID,
) -> InsuranceResponse:
    ins = await insurance_service.create_personal_insurance(user.id, family_id, request)
    return await detail(insurance_service, ins, True, can_edit=True)


@router.get("/{insurance_id}", response_model=InsuranceResponse)
async def get_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
) -> InsuranceResponse:
    ins = await _own(insurance_service, insurance_id, user.id)
    return await detail(insurance_service, ins, True, can_edit=True)


@router.patch("/{insurance_id}", response_model=InsuranceResponse)
async def update_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
    request: InsuranceUpdateRequest,
) -> InsuranceResponse:
    ins = await _own(insurance_service, insurance_id, user.id)
    updated = await insurance_service.update_insurance(ins, request, actor_id=user.id)
    return await detail(insurance_service, updated, True, can_edit=True)


@router.delete("/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
) -> None:
    ins = await _own(insurance_service, insurance_id, user.id)
    await insurance_service.delete_insurance(ins)
