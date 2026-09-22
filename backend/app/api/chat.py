"""
Chat Endpoints — RAG-powered Q&A with streaming
================================================

POST /api/chat/conversations              → Create new conversation
GET  /api/chat/conversations              → List conversations
GET  /api/chat/conversations/{id}         → Get conversation + messages
POST /api/chat/conversations/{id}/ask     → Ask a question (non-streaming)
POST /api/chat/conversations/{id}/stream  → Ask a question (streaming SSE)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User, Conversation, Message
from app.services.chat_service import chat, chat_stream

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=500)

class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    citations: Optional[list] = None
    created_at: str

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    document_ids: Optional[list[int]] = None  # None = search all documents

class AnswerResponse(BaseModel):
    answer: str
    citations: list


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=user.id, title=data.title)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConversationResponse(
        id=conv.id, title=conv.title,
        created_at=conv.created_at.isoformat(), updated_at=conv.updated_at.isoformat(),
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    convs = result.scalars().all()
    return [
        ConversationResponse(
            id=c.id, title=c.title,
            created_at=c.created_at.isoformat(), updated_at=c.updated_at.isoformat(),
        )
        for c in convs
    ]


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    msgs = result.scalars().all()
    return [
        MessageResponse(
            id=m.id, role=m.role, content=m.content,
            citations=m.citations, created_at=m.created_at.isoformat(),
        )
        for m in msgs
    ]


@router.post("/conversations/{conv_id}/ask", response_model=AnswerResponse)
async def ask_question(
    conv_id: int,
    req: QuestionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a question — retrieves relevant chunks, sends to LLM, returns answer with citations.
    """
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")

    response = await chat(db, user.id, conv_id, req.question, req.document_ids)
    return AnswerResponse(answer=response["answer"], citations=response["citations"])


@router.post("/conversations/{conv_id}/stream")
async def stream_answer(
    conv_id: int,
    req: QuestionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Streaming version — returns Server-Sent Events (SSE).
    
    The frontend uses EventSource or fetch with ReadableStream to consume this.
    Tokens arrive one at a time, creating a "typing" effect.
    """
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")

    return StreamingResponse(
        chat_stream(db, user.id, conv_id, req.question, req.document_ids),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
