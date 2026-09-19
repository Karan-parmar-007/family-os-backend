from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from uuid import UUID

from app.api.dependencies import DocumentServiceDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.routes.document.document_schemas import DocumentInfo, GetDocumentResponse

router = APIRouter(prefix="/families/{family_id}/documents", tags=["documents"])


@router.post(
    "",
    response_model=GetDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_family_document",
)
async def upload_family_document(
    family_id: UUID,
    service: DocumentServiceDep,
    current_user: LoggedInFamilyMemberDep,
    file: UploadFile = File(...),
) -> GetDocumentResponse:
    """Upload a document file for a family and return its metadata (id, filename)."""
    try:
        document = await service.store_family_document(family_id=family_id, file=file)
        return GetDocumentResponse(document=DocumentInfo.model_validate(document, from_attributes=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/{document_id}",
    response_model=GetDocumentResponse,
    status_code=200,
    operation_id="get_document",
)
async def get_document(
    document_id: UUID,
    family_id: UUID,
    service: DocumentServiceDep,
    current_user: LoggedInFamilyMemberDep,
) -> GetDocumentResponse:
    """Fetch document metadata by document_id."""
    document = await service.get_document(document_id=document_id)
    return GetDocumentResponse(document=DocumentInfo.model_validate(document, from_attributes=True))


@router.get(
    "/{document_id}/content",
    status_code=200,
    operation_id="get_document_content",
)
async def get_document_content(
    document_id: UUID,
    family_id: UUID,
    service: DocumentServiceDep,
    current_user: LoggedInFamilyMemberDep,
) -> Response:
    """Fetch document binary content from Garage storage."""
    document, content = await service.get_document_content(document_id=document_id)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.filename or "download"}"'},
    )
