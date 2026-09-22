"""
API Routes — Document Upload, Chat, Conversations
"""
from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router

router = APIRouter()
router.include_router(health_router, tags=["Health"])
router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(documents_router, prefix="/documents", tags=["Documents"])
router.include_router(chat_router, prefix="/chat", tags=["Chat"])
