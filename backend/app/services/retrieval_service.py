"""
Retrieval Service — Find relevant chunks using vector similarity
================================================================

This is the "R" in RAG (Retrieval-Augmented Generation).

Flow:
    User question: "What is the main conclusion?"
         ↓
    Convert question to embedding vector
         ↓
    pgvector: find chunks with most similar embeddings
         ↓
    Return top-K chunks as context
         ↓
    Pass context + question to LLM

pgvector operators:
    <->  L2 (Euclidean) distance
    <=>  Cosine distance         ← we use this (best for text similarity)
    <#>  Inner product distance
"""
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.services.embedding_service import get_embedding
from app.core.config import settings


async def retrieve_relevant_chunks(
    db: AsyncSession,
    query: str,
    user_id: int,
    document_ids: list[int] = None,
    top_k: int = None,
) -> list[dict]:
    """
    Find the most relevant document chunks for a query.
    
    1. Convert query to embedding
    2. Use pgvector cosine similarity to find nearest chunks
    3. Return top-K results with metadata
    
    Returns:
    [
        {
            "chunk_id": 42,
            "document_id": 1,
            "content": "The main conclusion is...",
            "page_number": 5,
            "similarity": 0.89,
            "filename": "research_paper.pdf"
        },
        ...
    ]
    """
    top_k = top_k or settings.TOP_K

    # Step 1: Convert query to vector
    query_embedding = await get_embedding(query)

    # Step 2: Build pgvector similarity search query
    # The <=> operator computes cosine distance (0 = identical, 2 = opposite)
    # We use 1 - distance to get similarity score (1 = identical, -1 = opposite)
    embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"
    
    sql = text("""
        SELECT 
            c.id as chunk_id,
            c.document_id,
            c.content,
            c.chunk_index,
            c.page_number,
            c.metadata,
            d.filename,
            1 - (c.embedding <=> :embedding::vector) as similarity
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE d.user_id = :user_id
        AND d.status = 'ready'
        AND c.embedding IS NOT NULL
    """)

    params = {
        "embedding": embedding_str,
        "user_id": user_id,
    }

    # Optional: filter by specific documents
    if document_ids:
        sql = text(str(sql) + " AND d.id = ANY(:doc_ids)")
        params["doc_ids"] = document_ids

    sql = text(str(sql) + " ORDER BY c.embedding <=> :embedding2::vector LIMIT :limit")
    params["embedding2"] = embedding_str
    params["limit"] = top_k

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "chunk_id": row.chunk_id,
            "document_id": row.document_id,
            "content": row.content,
            "chunk_index": row.chunk_index,
            "page_number": row.page_number,
            "filename": row.filename,
            "similarity": float(row.similarity) if row.similarity else 0.0,
        }
        for row in rows
    ]


def build_context(chunks: list[dict], max_tokens: int = None) -> str:
    """
    Build the context string from retrieved chunks.
    
    This is what gets injected into the LLM prompt as the "knowledge base".
    
    Format:
        [Source: paper.pdf, Page 3]
        The text content of chunk 1...
        
        [Source: paper.pdf, Page 5]
        The text content of chunk 2...
    """
    max_tokens = max_tokens or settings.MAX_CONTEXT_TOKENS
    
    context_parts = []
    total_chars = 0
    char_limit = max_tokens * 4  # rough estimate: 1 token ≈ 4 chars

    for chunk in chunks:
        source = f"[Source: {chunk['filename']}"
        if chunk.get('page_number'):
            source += f", Page {chunk['page_number']}"
        source += f", Relevance: {chunk['similarity']:.0%}]"
        
        chunk_text = f"{source}\n{chunk['content']}"
        
        if total_chars + len(chunk_text) > char_limit:
            break
        
        context_parts.append(chunk_text)
        total_chars += len(chunk_text)

    return "\n\n---\n\n".join(context_parts)
