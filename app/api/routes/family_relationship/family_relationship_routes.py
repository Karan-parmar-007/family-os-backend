from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.all_dependencies.part_of_the_family import LoggedInFamilyManagerDep, LoggedInFamilyMemberDep
from app.api.dependencies import FamilyRelationshipServiceDep
from app.api.routes.family_relationship.family_relationship_schemas import (
    FamilyConnectByCodeRequest,
    FamilyRelationshipCreateRequest,
    FamilyRelationshipListResponse,
    FamilyRelationshipResponse,
    FamilyJoinCodeResponse,
)

router = APIRouter(prefix="/families/{family_id}/relationships", tags=["family-relationships"])


@router.get("", response_model=FamilyRelationshipListResponse)
async def list_relationships(
    family_member: LoggedInFamilyMemberDep,
    relationship_service: FamilyRelationshipServiceDep,
    family_id: UUID,
) -> FamilyRelationshipListResponse:
    items = await relationship_service.list_relationships(family_id)
    return FamilyRelationshipListResponse(
        items=[FamilyRelationshipResponse.model_validate(item) for item in items]
    )


@router.get("/join-code", response_model=FamilyJoinCodeResponse)
async def get_join_code(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    family_id: UUID,
) -> FamilyJoinCodeResponse:
    try:
        code = await relationship_service.get_join_code(family_id)
        return FamilyJoinCodeResponse(join_code=code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/connect", response_model=FamilyRelationshipResponse, status_code=status.HTTP_201_CREATED)
async def connect_by_code(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    request: FamilyConnectByCodeRequest,
    family_id: UUID,
) -> FamilyRelationshipResponse:
    try:
        relationship = await relationship_service.connect_by_join_code(
            family_id=family_id,
            user_id=family_manager.id,
            request=request,
        )
        return FamilyRelationshipResponse.model_validate(relationship)
    except ValueError as exc:
        await relationship_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("", response_model=FamilyRelationshipResponse, status_code=status.HTTP_201_CREATED)
async def create_relationship(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    request: FamilyRelationshipCreateRequest,
    family_id: UUID,
) -> FamilyRelationshipResponse:
    try:
        relationship = await relationship_service.create_relationship_request(
            family_id=family_id,
            user_id=family_manager.id,
            request=request,
        )
        return FamilyRelationshipResponse.model_validate(relationship)
    except ValueError as exc:
        await relationship_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{relationship_id}/accept", response_model=FamilyRelationshipResponse)
async def accept_relationship(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    family_id: UUID,
    relationship_id: UUID,
) -> FamilyRelationshipResponse:
    relationship = await relationship_service.get_relationship(relationship_id)
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    try:
        accepted = await relationship_service.accept_relationship(
            family_id=family_id,
            user_id=family_manager.id,
            relationship=relationship,
        )
        return FamilyRelationshipResponse.model_validate(accepted)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await relationship_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{relationship_id}/reject", response_model=FamilyRelationshipResponse)
async def reject_relationship(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    family_id: UUID,
    relationship_id: UUID,
) -> FamilyRelationshipResponse:
    relationship = await relationship_service.get_relationship(relationship_id)
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    try:
        rejected = await relationship_service.reject_relationship(
            family_id=family_id,
            user_id=family_manager.id,
            relationship=relationship,
        )
        return FamilyRelationshipResponse.model_validate(rejected)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await relationship_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{relationship_id}", response_model=FamilyRelationshipResponse)
async def remove_relationship(
    family_manager: LoggedInFamilyManagerDep,
    relationship_service: FamilyRelationshipServiceDep,
    family_id: UUID,
    relationship_id: UUID,
) -> FamilyRelationshipResponse:
    relationship = await relationship_service.get_relationship(relationship_id)
    if relationship is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    try:
        removed = await relationship_service.remove_relationship(
            family_id=family_id,
            user_id=family_manager.id,
            relationship=relationship,
        )
        return FamilyRelationshipResponse.model_validate(removed)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await relationship_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
