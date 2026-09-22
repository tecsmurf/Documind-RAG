"""
Document Upload & Management Endpoints
=======================================

POST /api/documents/upload  → Upload a file → process → chunk → embed → store
GET  /api/documents         → List user's documents
GET  /api/documents/{id}    → Get document details + chunk count
DELETE /api/documents/{id}  → Delete document and all its chunks
"""
import os
import aiofiles
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User, Document, Chunk
from app.services.document_service import extract_text_from_file, clean_text, chunk_text
from app.services.embedding_service import get_embeddings_batch
from app.core.config import settings

router = APIRouter()


class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int
    total_chunks: int
    status: str
    error_message: Optional[str] = None
    created_at: str


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document, process it through the RAG pipeline.
    
    The complete pipeline:
    1. Save file to disk
    2. Extract text (PDF/TXT/MD)
    3. Clean text
    4. Split into chunks
    5. Generate embeddings for all chunks (batch API call)
    6. Store chunks + embeddings in pgvector
    7. Return document metadata
    """
    # Validate file type
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "txt", "md"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF, TXT, or MD.")

    # Validate file size
    content = await file.read()
    file_size = len(content)
    if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"File too large. Max: {settings.MAX_FILE_SIZE_MB}MB")

    # Create upload directory
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(settings.UPLOAD_DIR, f"{user.id}_{int(datetime.now().timestamp())}_{filename}")

    # Save file
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Create document record
    doc = Document(
        user_id=user.id,
        filename=filename,
        file_type=ext,
        file_size=file_size,
        status="processing",
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    try:
        # Step 2-3: Extract and clean text
        raw_text = extract_text_from_file(file_path, ext)
        cleaned_text = clean_text(raw_text)

        if not cleaned_text:
            raise ValueError("No text could be extracted from the file")

        # Step 4: Chunk the text
        chunks_data = chunk_text(cleaned_text)

        if not chunks_data:
            raise ValueError("Text could not be split into chunks")

        # Step 5: Generate embeddings for all chunks (single batch API call)
        chunk_texts = [c["content"] for c in chunks_data]
        embeddings = await get_embeddings_batch(chunk_texts)

        # Step 6: Store chunks with embeddings
        for chunk_info, embedding in zip(chunks_data, embeddings):
            chunk = Chunk(
                document_id=doc.id,
                content=chunk_info["content"],
                chunk_index=chunk_info["chunk_index"],
                page_number=chunk_info.get("page_number"),
                embedding=embedding,
            )
            db.add(chunk)

        # Step 7: Mark document as ready
        doc.total_chunks = len(chunks_data)
        doc.status = "ready"
        await db.flush()

    except Exception as e:
        doc.status = "error"
        doc.error_message = str(e)
        await db.flush()
        # Don't raise — return the document with error status

    # Clean up file (optional: keep for re-processing)
    try:
        os.remove(file_path)
    except OSError:
        pass

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        total_chunks=doc.total_chunks,
        status=doc.status,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat(),
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents for the current user."""
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        DocumentResponse(
            id=d.id, filename=d.filename, file_type=d.file_type,
            file_size=d.file_size, total_chunks=d.total_chunks,
            status=d.status, error_message=d.error_message,
            created_at=d.created_at.isoformat(),
        )
        for d in docs
    ]


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all its chunks/embeddings."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.user_id != user.id:
        raise HTTPException(403, "Access denied")
    await db.delete(doc)
    await db.flush()
