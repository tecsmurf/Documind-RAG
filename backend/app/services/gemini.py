"""
Google Gemini gateway (google-genai SDK, server-side only)
==========================================================

All Gemini traffic goes through this module so that:
- the API key stays on the server (it is only read from settings here);
- calls are async (client.aio) and never block the event loop;
- retries/timeouts are configured once (429 and 5xx are retried with backoff);
- provider errors are mapped to GeminiError with a *safe* user message. Raw
  Google error text is logged (it never contains the key) but never returned.

The client is created lazily so the app can boot (health checks, auth, listing)
even when GOOGLE_API_KEY is missing in development.
"""
import logging
from typing import AsyncIterator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


class GeminiError(Exception):
    """Gemini failure with a message that is safe to show to users."""

    def __init__(self, kind: str, user_message: str):
        super().__init__(kind)
        self.kind = kind
        self.user_message = user_message


_MESSAGES = {
    "not_configured": "The AI service is not configured. Please contact the administrator.",
    "auth": "The AI service rejected our credentials. Please contact the administrator.",
    "quota": "The AI service is busy or out of quota right now. Please try again in a minute.",
    "model_unavailable": "The AI model is currently unavailable. Please try again later.",
    "timeout": "The AI service took too long to respond. Please try again.",
    "blocked": "The AI service declined to answer this request.",
    "bad_response": "The AI service returned an unexpected response. Please try again.",
    "network": "Could not reach the AI service. Please try again.",
    "unknown": "The AI service failed to process the request. Please try again.",
}


def _error(kind: str) -> GeminiError:
    return GeminiError(kind, _MESSAGES[kind])


def get_client() -> genai.Client:
    global _client
    if not settings.GOOGLE_API_KEY:
        raise _error("not_configured")
    if _client is None:
        _client = genai.Client(
            api_key=settings.GOOGLE_API_KEY,
            http_options=types.HttpOptions(
                timeout=int(settings.GEMINI_TIMEOUT_SECONDS * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=settings.GEMINI_MAX_RETRIES + 1,
                    initial_delay=1.0,
                    max_delay=20.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )
    return _client


def map_exception(exc: BaseException) -> GeminiError:
    """Translate any SDK/network exception into a safe GeminiError and log the details."""
    if isinstance(exc, GeminiError):
        return exc
    kind = "unknown"
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        status = str(getattr(exc, "status", "") or "")
        if code in (401, 403) or "API_KEY" in str(exc) or status == "PERMISSION_DENIED":
            kind = "auth"
        elif code == 400 and "API key" in str(exc):
            kind = "auth"
        elif code == 429 or status == "RESOURCE_EXHAUSTED":
            kind = "quota"
        elif code == 404:
            kind = "model_unavailable"
        elif code in (408, 504) or status == "DEADLINE_EXCEEDED":
            kind = "timeout"
        elif code and code >= 500:
            kind = "model_unavailable"
        logger.warning("Gemini API error kind=%s code=%s status=%s", kind, code, status)
    elif isinstance(exc, TimeoutError) or type(exc).__name__ in ("ReadTimeout", "ConnectTimeout", "TimeoutException"):
        kind = "timeout"
        logger.warning("Gemini timeout: %s", type(exc).__name__)
    elif type(exc).__name__ in ("ConnectError", "NetworkError", "RemoteProtocolError", "ReadError"):
        kind = "network"
        logger.warning("Gemini network error: %s", type(exc).__name__)
    else:
        logger.exception("Unexpected Gemini error", exc_info=exc)
    return _error(kind)


async def embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """Embed a batch of texts. Raises GeminiError. Validates count and dimensions."""
    if not texts:
        return []
    try:
        result = await get_client().aio.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task_type),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a safe error
        raise map_exception(exc) from exc

    embeddings = getattr(result, "embeddings", None) or []
    if len(embeddings) != len(texts):
        logger.error("Embedding count mismatch: sent %d got %d", len(texts), len(embeddings))
        raise _error("bad_response")
    vectors = []
    for emb in embeddings:
        values = list(getattr(emb, "values", None) or [])
        if len(values) != settings.EMBEDDING_DIMENSIONS:
            logger.error("Embedding has %d dims, expected %d", len(values), settings.EMBEDDING_DIMENSIONS)
            raise _error("bad_response")
        vectors.append(values)
    return vectors


async def stream_generate(system_instruction: str, contents: list[types.Content]) -> AsyncIterator[str]:
    """Yield text fragments from Gemini. Raises GeminiError on failure or a blocked prompt."""
    try:
        stream = await get_client().aio.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
                max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        async for chunk in stream:
            feedback = getattr(chunk, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                logger.info("Gemini blocked prompt: %s", feedback.block_reason)
                raise _error("blocked")
            text = None
            try:
                text = chunk.text
            except (ValueError, AttributeError):
                text = None
            if text:
                yield text
            for cand in getattr(chunk, "candidates", None) or []:
                reason = str(getattr(cand, "finish_reason", "") or "")
                if any(r in reason for r in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "RECITATION")):
                    logger.info("Gemini stopped generation: %s", reason)
                    raise _error("blocked")
    except GeminiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise map_exception(exc) from exc
