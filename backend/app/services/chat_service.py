"""
Chat Service — RAG-powered conversational AI
=============================================

The complete RAG pipeline:

    User Question
         ↓
    Retrieve relevant chunks (retrieval_service)
         ↓
    Build context from chunks
         ↓
    Construct prompt: system + context + conversation history + question
         ↓
    Call OpenAI LLM
         ↓
    Stream response back with citations
         ↓
    Save to conversation history

This is the "AG" in RAG (Augmented Generation).
"""
import json
from typing import AsyncGenerator

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation, Message
from app.services.retrieval_service import retrieve_relevant_chunks, build_context

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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

    # Step 4: Construct messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        *history,
        {"role": "user", "content": question},
    ]

    # Step 5: Call LLM
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.1,  # Low temperature for factual answers
        max_tokens=2000,
    )

    answer = response.choices[0].message.content

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
    1. We send the request to OpenAI with stream=True
    2. OpenAI sends back tokens one at a time
    3. We yield each token immediately
    4. The frontend displays them as they arrive (SSE)
    
    The user sees the response being "typed" in real-time.
    """
    # Retrieve and build context (same as non-streaming)
    chunks = await retrieve_relevant_chunks(
        db, query=question, user_id=user_id, document_ids=document_ids
    )
    context = build_context(chunks)
    history = await get_conversation_history(db, conversation_id)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        *history,
        {"role": "user", "content": question},
    ]

    # Stream from OpenAI
    full_response = ""
    stream = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=2000,
        stream=True,
    )

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

    # Then stream the answer tokens
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            full_response += delta.content
            yield f"data: {json.dumps({'type': 'token', 'data': delta.content})}\n\n"

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
