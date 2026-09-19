from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import InsuranceServiceDep
from app.api.routes.insurance.insurance_routes import _resp
from app.api.routes.insurance.insurance_schemas import (
    InsuranceCreateRequest,
    InsuranceListResponse,
    InsuranceResponse,
    InsuranceUpdateRequest,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/personal/insurance", tags=["personal-insurance"])


@router.get("", response_model=InsuranceListResponse)
async def list_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    pagination: PaginationDep,
) -> InsuranceListResponse:
    items, total = await insurance_service.list_personal_insurances(user.id, pagination)
    return InsuranceListResponse.from_page(
        [_resp(i, True) for i in items], total=total, pagination=pagination
    )


@router.post("", response_model=InsuranceResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    request: InsuranceCreateRequest,
    family_id: UUID,
) -> InsuranceResponse:
    ins = await insurance_service.create_personal_insurance(user.id, family_id, request)
    return _resp(ins, True)


@router.get("/{insurance_id}", response_model=InsuranceResponse)
async def get_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
) -> InsuranceResponse:
    ins = await insurance_service.get_personal_insurance(insurance_id, user.id)
    if ins is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _resp(ins, True)


@router.patch("/{insurance_id}", response_model=InsuranceResponse)
async def update_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
    request: InsuranceUpdateRequest,
) -> InsuranceResponse:
    ins = await insurance_service.get_personal_insurance(insurance_id, user.id)
    if ins is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    updated = await insurance_service.update_insurance(ins, request)
    return _resp(updated, True)


@router.delete("/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_insurance(
    user: LoggedInUserDep,
    insurance_service: InsuranceServiceDep,
    insurance_id: UUID,
) -> None:
    ins = await insurance_service.get_personal_insurance(insurance_id, user.id)
    if ins is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await insurance_service.delete_insurance(ins)


@router.post("/{insurance_id}/pay-now", response_model=InsuranceResponse)
async def pay_now_personal_insurance(
    user: LoggedInUserDep,
    insurance_id: UUID,
) -> InsuranceResponse:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Pay now is removed. Insurance premiums apply via the mapped recurring expense.",
    )


@router.post("/{insurance_id}/split-plan", status_code=status.HTTP_410_GONE)
async def upsert_personal_insurance_split_plan(
    user: LoggedInUserDep,
    insurance_id: UUID,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Insurance funding splits are removed.",
    )
