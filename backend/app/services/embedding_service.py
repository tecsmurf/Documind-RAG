"""
Embedding Service — Convert text to vectors using OpenAI
========================================================

What are embeddings?
    Text → [0.023, -0.041, 0.089, ...] (1536 numbers)
    
    Similar text → similar vectors → can find by distance
    
    "Python programming"  → [0.1, 0.3, -0.2, ...]
    "Coding in Python"    → [0.1, 0.3, -0.2, ...]  ← SIMILAR vectors!
    "Cooking recipes"     → [-0.5, 0.1, 0.8, ...]  ← DIFFERENT vector

This is how RAG retrieval works:
    1. Convert user question to a vector
    2. Find the document chunks with the most similar vectors
    3. Those chunks are the relevant context for answering
"""
from openai import AsyncOpenAI

from app.core.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def get_embedding(text: str) -> list[float]:
    """Convert a single text to an embedding vector."""
    response = await client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Convert multiple texts to embedding vectors in one API call.
    
    Batching is important for cost and speed:
    - 1 API call for 100 texts instead of 100 separate calls
    - OpenAI embedding API supports up to 2048 inputs per batch
    """
    if not texts:
        return []

    # OpenAI allows max 2048 inputs per request
    batch_size = 2048
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = await client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=batch,
        )
        # Results come back in same order as input
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings
