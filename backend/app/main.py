"""
AI Document Intelligence — FastAPI Application
===============================================

Project 2: RAG (Retrieval-Augmented Generation) Application

Architecture:
    React Frontend
         ↓
    FastAPI API
         ↓
    Authentication (JWT — reused from Project 1)
         ↓
    Document Upload + Processing
         ↓
    Text Extraction → Chunking → Embeddings
         ↓
    pgvector (Vector Database)
         ↓
    Retrieval → Context Construction → LLM
         ↓
    Streaming Response → React
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="AI Document Intelligence",
    description="Upload documents, ask questions, get AI-powered answers with citations",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "app": "AI Document Intelligence",
        "version": "1.0.0",
        "docs": "/docs",
    }
