"""
Embedding service — text → 3072-dim vectors with gemini-embedding-001
=====================================================================

Documents are embedded with task type RETRIEVAL_DOCUMENT and questions with
RETRIEVAL_QUERY, which is how Gemini expects asymmetric search to be done.
Batches are capped by EMBEDDING_BATCH_SIZE; the SDK retries 429/5xx with
backoff. Any failure raises GeminiError, and the caller marks the document as
`error` without storing partial embeddings.
"""
from app.core.config import settings
from app.services import gemini


async def get_query_embedding(text: str) -> list[float]:
    vectors = await gemini.embed_texts([text], task_type="RETRIEVAL_QUERY")
    return vectors[0]


async def get_document_embeddings(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    size = settings.EMBEDDING_BATCH_SIZE
    for i in range(0, len(texts), size):
        vectors.extend(await gemini.embed_texts(texts[i : i + size], task_type="RETRIEVAL_DOCUMENT"))
    return vectors
