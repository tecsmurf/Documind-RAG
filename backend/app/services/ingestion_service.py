"""
Document ingestion pipeline
===========================

    processing/uploading → extracting → chunking → embedding → indexing → ready
                    └──────────── any failure ───────────────→ error

The upload request only validates the file and creates the `processing` row;
the pipeline runs in a background task with its own DB sessions so a slow
Gemini call never ties up the HTTP request.

Integrity rules:
- Chunks and their embeddings are written in ONE transaction together with
  status=ready. If anything fails before that, no chunk rows exist.
- Every failure sets status=error with a safe, user-facing message (never a
  raw exception string).
- Bounded by MAX_CONCURRENT_INGESTIONS and PROCESSING_TIMEOUT_SECONDS.
- Documents orphaned by a restart are reaped to `error` (reap_stale_documents).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.database.connection import async_session
from app.models import Chunk, Document
from app.models.models import DocumentStatus, ProcessingStage
from app.services.document_service import ProcessingFailed, chunk_pages, extract_pages
from app.services.embedding_service import get_document_embeddings
from app.services.gemini import GeminiError

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "Document processing failed. Try uploading the document again."
STALE_MESSAGE = "Processing was interrupted. Try uploading the document again."

_semaphore: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task] = set()


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_INGESTIONS)
    return _semaphore


def schedule_ingestion(document_id: int, data: bytes, file_type: str) -> asyncio.Task:
    task = asyncio.create_task(process_document(document_id, data, file_type), name=f"ingest-{document_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def wait_for_ingestions() -> None:
    """Used by tests and graceful shutdown."""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def _set_stage(document_id: int, stage: str, **fields) -> bool:
    """Commit a progress update. Returns False if the document was deleted meanwhile."""
    async with async_session() as db:
        result = await db.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.PROCESSING)
            .values(processing_stage=stage, updated_at=datetime.now(timezone.utc), **fields)
        )
        await db.commit()
        return result.rowcount > 0


async def _mark_error(document_id: int, message: str) -> None:
    try:
        async with async_session() as db:
            await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.ERROR,
                    error_message=message,
                    total_chunks=0,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Could not mark document %s as error", document_id)


async def process_document(document_id: int, data: bytes, file_type: str) -> None:
    try:
        async with asyncio.timeout(settings.PROCESSING_TIMEOUT_SECONDS):
            async with _get_semaphore():
                await _run_pipeline(document_id, data, file_type)
    except ProcessingFailed as exc:
        await _mark_error(document_id, exc.message)
    except GeminiError as exc:
        logger.warning("Embedding failed for document %s: %s", document_id, exc.kind)
        await _mark_error(document_id, f"Could not create embeddings. {exc.user_message}")
    except TimeoutError:
        await _mark_error(document_id, "Processing took too long. Try a smaller document.")
    except asyncio.CancelledError:
        await _mark_error(document_id, STALE_MESSAGE)
        raise
    except Exception:
        logger.exception("Unexpected ingestion failure for document %s", document_id)
        await _mark_error(document_id, GENERIC_FAILURE)


async def _run_pipeline(document_id: int, data: bytes, file_type: str) -> None:
    if not await _set_stage(document_id, ProcessingStage.EXTRACTING):
        return
    # Parsing is CPU-bound; keep it off the event loop.
    pages = await asyncio.to_thread(extract_pages, data, file_type)
    page_count = sum(1 for p in pages if p.page_number is not None) or None

    if not await _set_stage(document_id, ProcessingStage.CHUNKING, page_count=page_count):
        return
    chunks = await asyncio.to_thread(chunk_pages, pages)
    del pages
    if not chunks:
        if file_type == "pdf":
            raise ProcessingFailed("No readable text found. Scanned (image-only) PDFs are not supported.")
        raise ProcessingFailed("No readable text found in the document.")

    if not await _set_stage(document_id, ProcessingStage.EMBEDDING):
        return
    vectors = await get_document_embeddings([c["content"] for c in chunks])
    if len(vectors) != len(chunks):  # defensive: never store chunks without embeddings
        raise ProcessingFailed(GENERIC_FAILURE)

    if not await _set_stage(document_id, ProcessingStage.INDEXING):
        return
    async with async_session() as db:
        async with db.begin():
            doc = (
                await db.execute(select(Document).where(Document.id == document_id).with_for_update())
            ).scalar_one_or_none()
            if doc is None or doc.status != DocumentStatus.PROCESSING:
                return  # deleted (or reaped) while we were working
            await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            db.add_all(
                Chunk(
                    document_id=document_id,
                    content=c["content"],
                    chunk_index=c["chunk_index"],
                    page_number=c["page_number"],
                    embedding=v,
                )
                for c, v in zip(chunks, vectors)
            )
            doc.total_chunks = len(chunks)
            doc.status = DocumentStatus.READY
            doc.processing_stage = ProcessingStage.READY
            doc.error_message = None
            doc.updated_at = datetime.now(timezone.utc)
    logger.info("Document %s ready with %d chunks", document_id, len(chunks))


async def reap_stale_documents(user_id: int | None = None) -> int:
    """Mark documents stuck in `processing` past the timeout as error."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.PROCESSING_TIMEOUT_SECONDS + 60)
    stmt = (
        update(Document)
        .where(Document.status == DocumentStatus.PROCESSING, Document.updated_at < cutoff)
        .values(status=DocumentStatus.ERROR, error_message=STALE_MESSAGE, updated_at=datetime.now(timezone.utc))
    )
    if user_id is not None:
        stmt = stmt.where(Document.user_id == user_id)
    async with async_session() as db:
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0
