"""Shared API dependencies: authentication, client identity, rate limiting."""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import BucketPolicy, limiter
from app.core.security import decode_access_token
from app.database import get_db
from app.models import User
from app.services import auth_service

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Valid signature + unexpired + right issuer/type + user exists + active +
    token version matches (logout revokes). Every failure is the same 401.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "Not authenticated.", _UNAUTHORIZED)
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise AppError(401, "Session expired or invalid. Please sign in again.", _UNAUTHORIZED)
    user = await auth_service.get_user_by_id(db, payload["user_id"])
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise AppError(401, "Session expired or invalid. Please sign in again.", _UNAUTHORIZED)
    return user


def client_ip(request: Request) -> str:
    """
    Client IP behind TRUSTED_PROXY_HOPS reverse proxies (Render adds one).
    Uses the entry the trusted proxy appended, not the client-controlled left side.
    """
    hops = settings.TRUSTED_PROXY_HOPS
    forwarded = request.headers.get("x-forwarded-for", "")
    if hops and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-hops] if len(parts) >= hops else parts[0]
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(policy: BucketPolicy, identity: str) -> None:
    decision = await limiter.hit(policy, identity)
    if not decision.allowed:
        raise AppError(
            429,
            f"Too many requests. Please wait {decision.retry_after} seconds and try again.",
            {"Retry-After": str(max(1, decision.retry_after))},
        )
