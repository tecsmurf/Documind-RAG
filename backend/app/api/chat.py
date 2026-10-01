"""
Chat endpoints
==============

POST   /api/chat/conversations                  → create conversation
GET    /api/chat/conversations                  → list the caller's conversations
GET    /api/chat/conversations/{id}/messages    → messages (oldest first)
DELETE /api/chat/conversations/{id}             → delete conversation + messages
POST   /api/chat/conversations/{id}/ask         → answer (JSON, non-streaming)
POST   /api/chat/conversations/{id}/stream      → answer (SSE)

SSE events, one JSON object per `data:` line:
  {"type":"status","stage":"searching"|"retrieved"|"generating","count"?:n}
  {"type":"citations","data":[{index,document_id,chunk_id,filename,page_number,snippet,similarity}]}
  {"type":"token","data":"..."}
  {"type":"done","message_id":n}
  {"type":"error","message":"safe text","message_id":n|null}
"""
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit, get_current_user
from app.core import rate_limit
from app.core.config import settings
from app.core.errors import AppError
from app.database import get_db
from app.models import Conversation, Message, User
from app.services.chat_service import answer_once, stream_sse

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=200)

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = "".join(ch for ch in v if ch.isprintable()).strip()
        return v or "New Conversation"


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
    status: str = "complete"
    created_at: str


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    document_ids: Optional[list[int]] = Field(default=None, max_length=50)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question cannot be empty.")
        return v


class AnswerResponse(BaseModel):
    answer: str
    citations: list
    error: Optional[str] = None


def _conv_response(c: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=c.id, title=c.title, created_at=c.created_at.isoformat(), updated_at=c.updated_at.isoformat()
    )


async def _owned_conversation(db: AsyncSession, conv_id: int, user: User) -> Conversation:
    conv = (
        await db.execute(select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user.id))
    ).scalar_one_or_none()
    if conv is None:
        raise AppError(404, "Conversation not found.")
    return conv


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await enforce_rate_limit(rate_limit.CONVERSATION_USER, str(user.id))
    conv = Conversation(user_id=user.id, title=data.title)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return _conv_response(conv)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(200)
        )
    ).scalars().all()
    return [_conv_response(c) for c in convs]


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(conv_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_conversation(db, conv_id, user)
    msgs = (
        await db.execute(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id.asc()))
    ).scalars().all()
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            citations=m.citations,
            status=m.status or "complete",
            created_at=m.created_at.isoformat(),
        )
        for m in msgs
    ]


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conv = await _owned_conversation(db, conv_id, user)
    await db.execute(delete(Message).where(Message.conversation_id == conv.id))
    await db.delete(conv)


@router.post("/conversations/{conv_id}/ask", response_model=AnswerResponse)
async def ask_question(
    conv_id: int, req: QuestionRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _owned_conversation(db, conv_id, user)
    await enforce_rate_limit(rate_limit.CHAT_USER, str(user.id))
    await db.commit()  # release the request transaction before the long-running answer
    result = await answer_once(user.id, conv_id, req.question, req.document_ids)
    if result["error"] and not result["answer"]:
        raise AppError(502, result["error"])
    return AnswerResponse(**result)


@router.post("/conversations/{conv_id}/stream")
async def stream_answer(
    conv_id: int, req: QuestionRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    # Ownership + rate limit are checked before the stream starts, so failures are plain HTTP errors.
    await _owned_conversation(db, conv_id, user)
    await enforce_rate_limit(rate_limit.CHAT_USER, str(user.id))
    await db.commit()  # return the pooled connection; the stream may run for a while
    return StreamingResponse(
        # The generator opens its own DB sessions; it never touches this request's session.
        stream_sse(user.id, conv_id, req.question, req.document_ids),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
