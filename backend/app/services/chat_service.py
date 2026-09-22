"""
Chat Service — RAG-powered conversational AI (Google Gemini - FREE)
====================================================================

The complete RAG pipeline:

    User Question
         ↓
    Retrieve relevant chunks (retrieval_service)
         ↓
    Build context from chunks
         ↓
    Construct prompt: system + context + conversation history + question
         ↓
    Call Google Gemini LLM (FREE tier: 15 RPM, 1M TPM)
         ↓
    Stream response back with citations
         ↓
    Save to conversation history

Why Gemini instead of OpenAI?
    - Gemini 2.0 Flash is FREE (15 requests/min, 1500/day)
    - OpenAI GPT-4o-mini costs $0.15/1M input tokens
    - Quality is excellent for RAG use cases
"""
import json
from typing import AsyncGenerator

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation, Message
from app.services.retrieval_service import retrieve_relevant_chunks, build_context

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

SYSTEM_PROMPT = """You are an AI research assistant. You answer questions based on the provided document context.

RULES:
1. Answer ONLY based on the provided context. If the context doesn't contain the answer, say so.
2. Cite your sources using [Source: filename, Page X] format.
3. Be precise and factual. Do not make up information.
4. If multiple sources agree, mention that for reliability.
5. If sources contradict, note the disagreement.
6. Keep answers clear and well-structured.

CONTEXT FROM DOCUMENTS:
{context}
"""


async def get_conversation_history(db: AsyncSession, conversation_id: int, limit: int = 10) -> list[dict]:
    """Get recent messages from a conversation for context."""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()  # Oldest first
    return [{"role": m.role, "content": m.content} for m in messages]


def _build_gemini_contents(history: list[dict], question: str) -> list[types.Content]:
    """
    Build Gemini content list from conversation history + new question.
    Gemini uses 'user' and 'model' roles (not 'assistant').
    """
    contents = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    # Add the new question
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    return contents


async def chat(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    question: str,
    document_ids: list[int] = None,
) -> dict:
    """
    Non-streaming RAG chat.
    
    Returns: {"answer": "...", "citations": [...]}
    """
    # Step 1: Retrieve relevant chunks
    chunks = await retrieve_relevant_chunks(
        db, query=question, user_id=user_id, document_ids=document_ids
    )

    # Step 2: Build context
    context = build_context(chunks)

    # Step 3: Get conversation history
    history = await get_conversation_history(db, conversation_id)

    # Step 4: Build contents for Gemini
    contents = _build_gemini_contents(history, question)

    # Step 5: Call Gemini
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(context=context),
            temperature=0.1,
            max_output_tokens=2000,
        ),
    )

    answer = response.text

    # Step 6: Build citations from retrieved chunks
    citations = [
        {
            "document_id": c["document_id"],
            "chunk_id": c["chunk_id"],
            "filename": c["filename"],
            "page_number": c.get("page_number"),
            "content": c["content"][:200] + "..." if len(c["content"]) > 200 else c["content"],
            "similarity": round(c["similarity"], 3),
        }
        for c in chunks
    ]

    # Step 7: Save messages to conversation
    user_msg = Message(conversation_id=conversation_id, role="user", content=question)
    assistant_msg = Message(
        conversation_id=conversation_id, role="assistant",
        content=answer, citations=citations,
    )
    db.add(user_msg)
    db.add(assistant_msg)
    await db.flush()

    return {"answer": answer, "citations": citations}


async def chat_stream(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    question: str,
    document_ids: list[int] = None,
) -> AsyncGenerator[str, None]:
    """
    Streaming RAG chat — yields tokens as they're generated.
    
    This is how ChatGPT-style streaming works:
    1. We send the request to Gemini with stream=True
    2. Gemini sends back chunks of text
    3. We yield each chunk immediately
    4. The frontend displays them as they arrive (SSE)
    
    The user sees the response being "typed" in real-time.
    """
    # Retrieve and build context (same as non-streaming)
    chunks = await retrieve_relevant_chunks(
        db, query=question, user_id=user_id, document_ids=document_ids
    )
    context = build_context(chunks)
    history = await get_conversation_history(db, conversation_id)

    # Build contents for Gemini
    contents = _build_gemini_contents(history, question)

    # Build citations
    citations = [
        {
            "document_id": c["document_id"],
            "chunk_id": c["chunk_id"],
            "filename": c["filename"],
            "page_number": c.get("page_number"),
            "content": c["content"][:200],
            "similarity": round(c["similarity"], 3),
        }
        for c in chunks
    ]

    # First, send citations as a special event
    yield f"data: {json.dumps({'type': 'citations', 'data': citations})}\n\n"

    # Stream from Gemini
    full_response = ""
    response = client.models.generate_content_stream(
        model=settings.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(context=context),
            temperature=0.1,
            max_output_tokens=2000,
        ),
    )

    for chunk in response:
        if chunk.text:
            full_response += chunk.text
            yield f"data: {json.dumps({'type': 'token', 'data': chunk.text})}\n\n"

    # Signal completion
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # Save to conversation history
    user_msg = Message(conversation_id=conversation_id, role="user", content=question)
    assistant_msg = Message(
        conversation_id=conversation_id, role="assistant",
        content=full_response, citations=citations,
    )
    db.add(user_msg)
    db.add(assistant_msg)
    await db.flush()
