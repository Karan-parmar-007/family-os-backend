import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import uuid6
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.document.model import Document
from app.config import db_settings, feature_settings
from app.core.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


def _maybe_encrypt(content: bytes) -> bytes:
    return encrypt(content)


def _maybe_decrypt(content: bytes) -> bytes:
    if not feature_settings.FEATURE_ENCRYPTION:
        return content
    if len(content) > 1 and content[0] < 32:
        try:
            return decrypt(content)
        except Exception:
            logger.warning("Failed to decrypt document blob; returning raw bytes")
    return content


class DocumentService:
    def __init__(self, pg_session: AsyncSession, garage_client: Any):
        self.pg_session = pg_session
        self.garage_client = garage_client

    async def store_family_document(
        self,
        family_id: UUID,
        file: UploadFile,
    ) -> Document:
        """Upload a file to Garage and persist document metadata in Postgres."""
        content = await file.read()
        if not content:
            raise ValueError("Document file is empty")

        safe_filename = os.path.basename(file.filename or "") or "upload"
        document_id = uuid6.uuid7()
        object_key = f"families/{family_id}/documents/{document_id}/{safe_filename}"

        stored_body = _maybe_encrypt(content)
        await self.garage_client.put_object(
            Bucket=db_settings.GARAGE_BUCKET_NAME,
            Key=object_key,
            Body=stored_body,
            ContentType=file.content_type or "application/octet-stream",
        )

        document = Document(
            id=document_id,
            filename=safe_filename,
            file_path=object_key,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.pg_session.add(document)
        await self.pg_session.commit()
        await self.pg_session.refresh(document)
        return document

    async def store_user_document(
        self,
        user_id: UUID,
        file: UploadFile,
    ) -> Document:
        """Upload a file to the user's personal document namespace."""
        content = await file.read()
        if not content:
            raise ValueError("Document file is empty")

        safe_filename = os.path.basename(file.filename or "") or "upload"
        document_id = uuid6.uuid7()
        object_key = f"users/{user_id}/documents/{document_id}/{safe_filename}"

        stored_body = _maybe_encrypt(content)
        await self.garage_client.put_object(
            Bucket=db_settings.GARAGE_BUCKET_NAME,
            Key=object_key,
            Body=stored_body,
            ContentType=file.content_type or "application/octet-stream",
        )

        document = Document(
            id=document_id,
            filename=safe_filename,
            file_path=object_key,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.pg_session.add(document)
        await self.pg_session.commit()
        await self.pg_session.refresh(document)
        return document

    def user_owns_document(self, user_id: UUID, document: Document) -> bool:
        prefix = f"users/{user_id}/documents/"
        return bool(document.file_path and document.file_path.startswith(prefix))

    async def delete_document(self, document_id: UUID) -> None:
        """Remove a document from Garage and delete its metadata row."""
        stmt = select(Document).where(Document.id == document_id)
        result = await self.pg_session.execute(stmt)
        document = result.scalar_one_or_none()
        if document is None:
            return

        if document.file_path:
            await self.garage_client.delete_object(
                Bucket=db_settings.GARAGE_BUCKET_NAME,
                Key=document.file_path,
            )

        await self.pg_session.delete(document)
        await self.pg_session.commit()

    async def replace_family_document(
        self,
        family_id: UUID,
        file: UploadFile,
        old_document_id: UUID | None,
    ) -> Document:
        """Delete the old document (if any), then upload and persist a new one."""
        if old_document_id is not None:
            await self.delete_document(old_document_id)
        return await self.store_family_document(family_id=family_id, file=file)

    async def get_document(self, document_id: UUID) -> Document:
        """Fetch document metadata from Postgres by document_id."""
        stmt = select(Document).where(Document.id == document_id)
        result = await self.pg_session.execute(stmt)
        document = result.scalar_one_or_none()
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    async def get_document_content(self, document_id: UUID) -> tuple[Document, bytes]:
        """Fetch document metadata and its binary content from Garage."""
        document = await self.get_document(document_id)

        response = await self.garage_client.get_object(
            Bucket=db_settings.GARAGE_BUCKET_NAME,
            Key=document.file_path,
        )
        content = await response["Body"].read()
        content = _maybe_decrypt(content)

        return document, content
