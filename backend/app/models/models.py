"""
Database Models for RAG Application
====================================

Schema:
    users          → authentication
    documents      → uploaded files
    chunks         → text chunks from documents (with embeddings)
    conversations  → chat sessions
    messages       → individual messages in conversations

The KEY table is 'chunks' — it stores:
    - The text content of each chunk
    - The vector embedding (1536-dim float array)
    - Metadata (page number, source document)
    
pgvector lets us do: SELECT * FROM chunks ORDER BY embedding <=> query_embedding LIMIT 5
This finds the 5 most similar chunks to a query — the core of RAG retrieval.
"""
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import String, Integer, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database.connection import Base
from app.core.config import settings


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)  # pdf, txt, md
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="processing")  # processing, ready, error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", back_populates="documents")
    chunks: Mapped[List["Chunk"]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """
    A chunk of text from a document, with its vector embedding.
    
    This is the heart of RAG:
    1. Documents are split into chunks
    2. Each chunk is converted to a vector embedding
    3. When user asks a question, we find the most similar chunks
    4. Those chunks become the context for the LLM
    """
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # Position in document
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    # THE VECTOR EMBEDDING — 1536 dimensions from OpenAI text-embedding-3-small
    embedding = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # [{doc_id, chunk_id, text}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
