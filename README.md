# Project 2 — AI Document Intelligence (RAG Application)

## What It Does
Upload PDF/TXT/MD documents → Ask questions → Get AI answers with citations from your documents.

## Architecture
```
React Frontend
     ↓
FastAPI Backend
     ↓
Document Upload → Text Extraction → Chunking → Embeddings (OpenAI)
     ↓
pgvector (PostgreSQL + Vector Search)
     ↓
User Question → Retrieve relevant chunks → LLM with context → Streaming answer
```

## Setup
```bash
# 1. Add your OpenAI API key to backend/.env
# 2. Start with Docker Compose
docker compose up --build

# Or run locally:
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## API Endpoints
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /api/auth/register | Register |
| POST | /api/auth/login | Login |
| POST | /api/documents/upload | Upload document → process → embed |
| GET | /api/documents | List documents |
| DELETE | /api/documents/{id} | Delete document |
| POST | /api/chat/conversations | Create conversation |
| GET | /api/chat/conversations | List conversations |
| POST | /api/chat/conversations/{id}/ask | Ask question (non-streaming) |
| POST | /api/chat/conversations/{id}/stream | Ask question (SSE streaming) |

## Key Files
- `services/document_service.py` — Text extraction, cleaning, chunking
- `services/embedding_service.py` — OpenAI embeddings (text → vectors)
- `services/retrieval_service.py` — pgvector similarity search
- `services/chat_service.py` — RAG pipeline: retrieve → context → LLM → answer
- `models/models.py` — Database schema with pgvector embedding column
