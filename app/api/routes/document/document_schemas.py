"""Pydantic schemas for document routes."""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    """Metadata for a stored document."""
    id: UUID
    filename: Optional[str] = None
    file_path: Optional[str] = None


class GetDocumentResponse(BaseModel):
    """Response wrapper for get_document endpoint."""
    document: DocumentInfo

