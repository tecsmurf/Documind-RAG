"""
Embedding Service — Convert text to vectors using Google Gemini (FREE)
======================================================================

What are embeddings?
    Text → [0.023, -0.041, 0.089, ...] (3072 numbers with Gemini)
    
    Similar text → similar vectors → can find by distance
    
    "Python programming"  → [0.1, 0.3, -0.2, ...]
    "Coding in Python"    → [0.1, 0.3, -0.2, ...]  ← SIMILAR vectors!
    "Cooking recipes"     → [-0.5, 0.1, 0.8, ...]  ← DIFFERENT vector

Why Gemini instead of OpenAI?
    - Google Gemini gemini-embedding-001 is FREE (1500 requests/day)
    - OpenAI text-embedding-3-small costs $0.02/1M tokens
    - Quality is comparable for RAG use cases
"""
from google import genai

from app.core.config import settings

client = genai.Client(api_key=settings.GOOGLE_API_KEY)


async def get_embedding(text: str) -> list[float]:
    """Convert a single text to an embedding vector using Gemini."""
    result = client.models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=text,
    )
    return list(result.embeddings[0].values)


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Convert multiple texts to embedding vectors.
    
    Gemini embed_content supports batching natively — pass a list of strings
    and get back a list of embeddings in one API call.
    """
    if not texts:
        return []

    # Process in batches of 100 to avoid potential limits
    batch_size = 100
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = client.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=batch,
        )
        for emb in result.embeddings:
            all_embeddings.append(list(emb.values))

    return all_embeddings
