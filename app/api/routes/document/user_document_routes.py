from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from uuid import UUID

from app.api.dependencies import DocumentServiceDep
from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.routes.document.document_schemas import DocumentInfo, GetDocumentResponse

router = APIRouter(prefix="/user/documents", tags=["user-documents"])

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024  # 25MB


@router.post(
    "",
    response_model=GetDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_user_document",
)
async def upload_user_document(
    service: DocumentServiceDep,
    current_user: LoggedInUserDep,
    file: UploadFile = File(...),
) -> GetDocumentResponse:
    """Upload a personal document for the current user and return its metadata."""
    if file.size and file.size > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB",
        )
    try:
        document = await service.store_user_document(user_id=current_user.id, file=file)
        return GetDocumentResponse(document=DocumentInfo.model_validate(document, from_attributes=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/{document_id}",
    response_model=GetDocumentResponse,
    status_code=200,
    operation_id="get_user_document",
)
async def get_user_document(
    document_id: UUID,
    service: DocumentServiceDep,
    current_user: LoggedInUserDep,
) -> GetDocumentResponse:
    document = await service.get_document(document_id=document_id)
    if not service.user_owns_document(current_user.id, document):
        raise HTTPException(status_code=403, detail="Document access denied")
    return GetDocumentResponse(document=DocumentInfo.model_validate(document, from_attributes=True))


@router.get(
    "/{document_id}/content",
    status_code=200,
    operation_id="get_user_document_content",
)
async def get_user_document_content(
    document_id: UUID,
    service: DocumentServiceDep,
    current_user: LoggedInUserDep,
) -> Response:
    document = await service.get_document(document_id=document_id)
    if not service.user_owns_document(current_user.id, document):
        raise HTTPException(status_code=403, detail="Document access denied")
    document, content = await service.get_document_content(document_id=document_id)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.filename or "download"}"'},
    )
