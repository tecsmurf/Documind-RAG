"""
Retrieval — user-scoped pgvector similarity search
==================================================

    User → their READY documents → those documents' chunks → cosine distance → top-K

The ownership filter (documents.user_id = :user) is part of the same SQL
statement as the vector search, so a user can never retrieve another user's
chunks, even when passing someone else's document ids.

Query uses SQLAlchemy + pgvector's comparator (`embedding <=> :vec`), with the
vector bound as a proper parameter. (The old raw SQL `:embedding::vector`
was parsed by SQLAlchemy as a bind named `embeddin` and failed every time.)
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Chunk, Document
from app.models.models import DocumentStatus
from app.services.embedding_service import get_query_embedding


async def search_chunks(
    db: AsyncSession,
    query_embedding: list[float],
    user_id: int,
    document_ids: list[int] | None = None,
    top_k: int | None = None,
) -> list[dict]:
    top_k = top_k or settings.TOP_K
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.content,
            Chunk.chunk_index,
            Chunk.page_number,
            Document.filename,
            distance,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(
            Document.user_id == user_id,
            Document.status == DocumentStatus.READY,
            Chunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
    )
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))

    rows = (await db.execute(stmt)).all()
    return [
        {
            "chunk_id": r.id,
            "document_id": r.document_id,
            "content": r.content,
            "chunk_index": r.chunk_index,
            "page_number": r.page_number,
            "filename": r.filename,
            "similarity": max(-1.0, min(1.0, 1.0 - float(r.distance))) if r.distance is not None else 0.0,
        }
        for r in rows
    ]


async def retrieve_relevant_chunks(
    db: AsyncSession,
    query: str,
    user_id: int,
    document_ids: list[int] | None = None,
    top_k: int | None = None,
) -> list[dict]:
    embedding = await get_query_embedding(query)
    return await search_chunks(db, embedding, user_id, document_ids, top_k)


def select_context_chunks(chunks: list[dict], max_chars: int | None = None) -> list[dict]:
    """Keep chunks in rank order until the context budget is spent."""
    budget = max_chars or settings.MAX_CONTEXT_CHARS
    selected, used = [], 0
    for chunk in chunks:
        size = len(chunk["content"])
        if selected and used + size > budget:
            break
        if not selected and size > budget:
            chunk = {**chunk, "content": chunk["content"][:budget]}
            size = budget
        selected.append(chunk)
        used += size
    return selected
