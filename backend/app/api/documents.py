"""
Document endpoints
==================

POST   /api/documents/upload                     → validate, create `processing` row, ingest in background
GET    /api/documents                            → list the caller's documents (with live processing stage)
GET    /api/documents/{id}                       → one document
GET    /api/documents/{id}/chunks/{chunk_id}     → one passage (used to open a citation)
DELETE /api/documents/{id}                       → delete document + chunks

Every lookup filters on user_id in SQL. Another user's id gives the same 404
as a missing id, so ids cannot be probed.
"""
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit, get_current_user
from app.core import rate_limit
from app.core.config import settings
from app.core.errors import AppError
from app.database import get_db
from app.models import Chunk, Document, User
from app.models.models import DocumentStatus, ProcessingStage
from app.services.document_service import DocumentRejected, sanitize_filename, validate_upload
from app.services.ingestion_service import reap_stale_documents, schedule_ingestion

router = APIRouter()

_READ_BLOCK = 1024 * 1024


class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int
    total_chunks: int
    status: str
    processing_stage: Optional[str] = None
    page_count: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class ChunkResponse(BaseModel):
    id: int
    document_id: int
    filename: str
    chunk_index: int
    page_number: Optional[int] = None
    content: str


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def to_response(d: Document) -> DocumentResponse:
    return DocumentResponse(
        id=d.id,
        filename=d.filename,
        file_type=d.file_type,
        file_size=d.file_size,
        total_chunks=d.total_chunks or 0,
        status=d.status,
        processing_stage=d.processing_stage,
        page_count=d.page_count,
        error_message=d.error_message if d.status == DocumentStatus.ERROR else None,
        created_at=_iso(d.created_at),
        updated_at=_iso(d.updated_at),
    )


async def _owned_document(db: AsyncSession, doc_id: int, user: User) -> Document:
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id, Document.user_id == user.id))
    ).scalar_one_or_none()
    if doc is None:
        raise AppError(404, "Document not found.")
    return doc


async def _read_limited(file: UploadFile) -> bytes:
    """Read at most MAX_FILE_SIZE + 1 bytes (the middleware already caps the body)."""
    limit = settings.max_file_size_bytes
    buf = bytearray()
    while True:
        block = await file.read(_READ_BLOCK)
        if not block:
            break
        buf.extend(block)
        if len(buf) > limit:
            raise AppError(413, f"File is too large. The maximum size is {settings.MAX_FILE_SIZE_MB} MB.")
    return bytes(buf)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(rate_limit.UPLOAD_USER, str(user.id))

    filename = sanitize_filename(file.filename)
    data = await _read_limited(file)
    try:
        file_type = validate_upload(filename, data)
    except DocumentRejected as exc:
        raise AppError(exc.status_code, exc.message) from None

    content_hash = hashlib.sha256(data).hexdigest()
    existing = (
        await db.execute(
            select(Document).where(Document.user_id == user.id, Document.content_hash == content_hash)
        )
    ).scalars().all()
    if any(d.status in (DocumentStatus.READY, DocumentStatus.PROCESSING) for d in existing):
        raise AppError(409, "You have already uploaded this document.")
    # Re-uploading a file that previously failed replaces the failed entry.
    for failed in existing:
        await db.delete(failed)

    count = (
        await db.execute(select(func.count()).select_from(Document).where(Document.user_id == user.id))
    ).scalar_one()
    if count - len(existing) >= settings.MAX_DOCUMENTS_PER_USER:
        raise AppError(400, f"Document limit reached ({settings.MAX_DOCUMENTS_PER_USER}). Delete a document first.")

    doc = Document(
        user_id=user.id,
        filename=filename,
        file_type=file_type,
        file_size=len(data),
        status=DocumentStatus.PROCESSING,
        processing_stage=ProcessingStage.UPLOADING,
        content_hash=content_hash,
        total_chunks=0,
    )
    db.add(doc)
    await db.commit()  # the background task reads this row with its own session
    await db.refresh(doc)
    schedule_ingestion(doc.id, data, file_type)
    return to_response(doc)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await reap_stale_documents(user.id)
    docs = (
        await db.execute(
            select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc(), Document.id.desc())
        )
    ).scalars().all()
    return [to_response(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return to_response(await _owned_document(db, doc_id, user))


@router.get("/{doc_id}/chunks/{chunk_id}", response_model=ChunkResponse)
async def get_chunk(
    doc_id: int, chunk_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    row = (
        await db.execute(
            select(Chunk.id, Chunk.document_id, Chunk.chunk_index, Chunk.page_number, Chunk.content, Document.filename)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id == chunk_id, Chunk.document_id == doc_id, Document.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "Passage not found.")
    return ChunkResponse(
        id=row.id,
        document_id=row.document_id,
        filename=row.filename,
        chunk_index=row.chunk_index,
        page_number=row.page_number,
        content=row.content,
    )


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await _owned_document(db, doc_id, user)
    await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    await db.delete(doc)
