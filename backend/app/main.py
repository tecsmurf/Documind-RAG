"""
DocuMind — FastAPI application
==============================

    React (Vercel) ──REST + SSE──► FastAPI (Render)
                                     ├── /api/auth       JWT auth, rate-limited login
                                     ├── /api/documents  upload → extract → chunk → embed → pgvector
                                     ├── /api/chat       user-scoped retrieval → Gemini → SSE
                                     └── /api/health     liveness + readiness
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG and not settings.is_production else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("documind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_startup()  # refuses to boot with unsafe production config
    await init_db()
    from app.services.ingestion_service import reap_stale_documents, wait_for_ingestions

    reaped = await reap_stale_documents()
    if reaped:
        logger.warning("Marked %d interrupted document(s) as error", reaped)
    logger.info("DocuMind started (environment=%s)", settings.ENVIRONMENT)
    yield
    await wait_for_ingestions()


def create_app() -> FastAPI:
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="DocuMind API",
        description="Upload documents, ask questions, get AI answers with citations",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # The last middleware added runs first. CORS is outermost so even 413/429/500
    # responses carry CORS headers and the browser can show the real error.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=settings.allowed_origin_regex,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After", "X-Request-ID"],
        max_age=600,
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    async def root():
        return {"app": "DocuMind", "status": "ok"}

    return app


app = create_app()
