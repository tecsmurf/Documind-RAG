"""
GET /api/health        → liveness (process is up; no dependencies touched)
GET /api/health/ready  → readiness: database, pgvector, vector(3072) column, Gemini key present.
                         Booleans only; never echoes configuration values.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.database.connection import check_database

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "DocuMind"}


@router.get("/health/ready")
async def readiness():
    checks = await check_database()
    checks["gemini_configured"] = bool(settings.GOOGLE_API_KEY)
    ok = all(checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)
