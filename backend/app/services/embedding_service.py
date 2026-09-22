"""
Embedding Service — Convert text to vectors using Google Gemini (FREE)
======================================================================

What are embeddings?
    Text → [0.023, -0.041, 0.089, ...] (768 numbers with Gemini)
    
    Similar text → similar vectors → can find by distance
    
    "Python programming"  → [0.1, 0.3, -0.2, ...]
    "Coding in Python"    → [0.1, 0.3, -0.2, ...]  ← SIMILAR vectors!
    "Cooking recipes"     → [-0.5, 0.1, 0.8, ...]  ← DIFFERENT vector

Why Gemini instead of OpenAI?
    - Google Gemini text-embedding-004 is FREE (1500 requests/day)
    - OpenAI text-embedding-3-small costs $0.02/1M tokens
    - Quality is comparable for RAG use cases
"""
import google.generativeai as genai

from app.core.config import settings

genai.configure(api_key=settings.GOOGLE_API_KEY)


async def get_embedding(text: str) -> list[float]:
    """Convert a single text to an embedding vector using Gemini."""
    result = genai.embed_content(
        model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Convert multiple texts to embedding vectors.
    
    Gemini embed_content supports batching natively — pass a list of strings
    and get back a list of embeddings in one API call.
    """
    if not texts:
        return []

    # Gemini supports batch embedding — pass list of texts
    # Process in batches of 100 to avoid potential limits
    batch_size = 100
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = genai.embed_content(
            model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
            content=batch,
            task_type="retrieval_document",
        )
        all_embeddings.extend(result["embedding"])

    return all_embeddings
