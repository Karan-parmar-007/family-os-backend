import logging

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUserDep, FamilyServiceDep
from app.api.routes.family.family_schemas import (
    FamilyCreateRequest,
    FamilyCreateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/families", tags=["families"])


@router.post(
    "",
    response_model=FamilyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new family",
    description="Create a family and automatically link the creator as the family manager.",
)
async def create_family(
    request: FamilyCreateRequest,
    family_service: FamilyServiceDep,
    current_user: CurrentUserDep,
) -> FamilyCreateResponse:
    """Create a new family with the authenticated user as the manager."""
    try:
        await family_service.create_family(
            user_id=current_user.id,
            family_name=request.name,
            currency=request.currency,
        )
        
        return FamilyCreateResponse(message="Family created successfully")
    except Exception as e:
        await family_service.pg_session.rollback()
        logger.error(f"Error creating family: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create family",
        )
