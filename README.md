# DocuMind — AI Document Intelligence (RAG)

Upload PDF / TXT / MD documents, ask questions, and get answers grounded in your files with numbered, clickable citations.

```
React 19 + Vite (Vercel) ──REST + SSE──► FastAPI (Render, Docker)
                                           ├── /api/auth       JWT, bcrypt, token-bucket login limits
                                           ├── /api/documents  validate → extract → chunk → embed (background)
                                           ├── /api/chat       user-scoped pgvector search → Gemini → SSE
                                           └── /api/health     liveness + /health/ready
                                                  │
                         PostgreSQL + pgvector (Neon) · Google Gemini (google-genai, server-side only)
```

- LLM: `gemini-2.0-flash` (configurable via `GEMINI_MODEL`)
- Embeddings: `gemini-embedding-001`, 3072 dimensions
- Schema: Alembic migrations in `backend/migrations` (run automatically by the container; never drops data)

## Run locally

```bash
cp .env.example .env            # set GOOGLE_API_KEY (and a SECRET_KEY)
docker compose up --build       # db :5432, api :8000, web :5173
```

Without Docker: Postgres 16 with pgvector, then

```bash
cd backend && pip install -r requirements-dev.txt
alembic upgrade head && uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev
```

## Tests

```bash
# backend: real Postgres+pgvector test DB (name must end in _test), Gemini faked
createdb documind_test && cd backend && pytest
# frontend unit tests
cd frontend && npm test
# browser E2E: backend with fake Gemini + production build
cd backend && DATABASE_URL=.../documind_e2e alembic upgrade head && E2E_PORT=8010 python -m tests.e2e_server
cd frontend && VITE_API_URL=http://localhost:8010 npm run build && npx vite preview --port 4173 & npm run test:e2e
```

## Production configuration

Render (backend) — required:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon URL (`?sslmode=require` is fine) |
| `SECRET_KEY` | ≥32 random chars: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_API_KEY` | Gemini key |
| `ALLOWED_ORIGINS` | exact frontend origin(s), e.g. `https://your-app.vercel.app` |
| `DEBUG` | `false` (or unset) |

On Render the app defaults to `ENVIRONMENT=production` and refuses to start if any of these are unsafe or missing. Optional: `REDIS_URL` (required only if `WEB_CONCURRENCY` > 1), `MAX_FILE_SIZE_MB` (default 10), `GEMINI_MODEL`.

Vercel (frontend): `VITE_API_URL=https://<your-render-service>.onrender.com`, then **redeploy** (Vite bakes it in at build time). If the backend URL changes, also update `connect-src` in `frontend/vercel.json`.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/auth/register | Register (returns token) |
| POST | /api/auth/login | Login (form: username=email, password) |
| GET | /api/auth/me | Current user |
| POST | /api/auth/logout | Revoke all of the user's tokens |
| POST | /api/documents/upload | Validate and queue a document |
| GET | /api/documents | List documents (status, stage, chunks, pages) |
| GET | /api/documents/{id} | One document |
| GET | /api/documents/{id}/chunks/{chunk_id} | Passage behind a citation |
| DELETE | /api/documents/{id} | Delete document and chunks |
| POST/GET | /api/chat/conversations | Create / list conversations |
| GET | /api/chat/conversations/{id}/messages | Messages (with status) |
| DELETE | /api/chat/conversations/{id} | Delete conversation |
| POST | /api/chat/conversations/{id}/stream | Ask (SSE) |
| POST | /api/chat/conversations/{id}/ask | Ask (JSON) |
| GET | /api/health, /api/health/ready | Liveness / readiness |
