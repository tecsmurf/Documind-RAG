"""
Auth endpoints
==============

POST /api/auth/register  → create account, returns a token
POST /api/auth/login     → OAuth2 password form (username = email), returns a token
GET  /api/auth/me        → current user
POST /api/auth/logout    → revokes every token issued to this user (token_version++)

Login is rate limited with token buckets per account (50, +1 every 1.2 s) and
per client IP, and always answers "Invalid email or password." for unknown
emails, wrong passwords and disabled accounts alike.
"""
import unicodedata

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, enforce_rate_limit, get_current_user
from app.core import rate_limit
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import BCRYPT_MAX_BYTES, create_access_token
from app.database import get_db
from app.models import User
from app.services import auth_service

router = APIRouter()

INVALID_LOGIN = "Invalid email or password."


class UserCreate(BaseModel):
    email: EmailStr = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = "".join(ch for ch in v if unicodedata.category(ch)[0] != "C").strip()
        if not v:
            raise ValueError("Name is required.")
        return v

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes.")
        if v.strip() == "":
            raise ValueError("Password cannot be blank.")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str


def _token_for(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, user.token_version),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/register", response_model=Token, status_code=201)
async def register(data: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    await enforce_rate_limit(rate_limit.REGISTER_IP, client_ip(request))
    try:
        user = await auth_service.create_user(db, data.email, data.password, data.full_name)
    except auth_service.EmailTaken:
        # Registration inherently reveals that an email is taken; it is rate limited per IP.
        raise AppError(409, "An account with this email already exists.") from None
    return _token_for(user)


@router.post("/login", response_model=Token)
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    email = auth_service.normalize_email(form.username or "")[:254]
    password = (form.password or "")[:256]
    # IP first so one client can't drain many accounts' buckets; then the account bucket.
    await enforce_rate_limit(rate_limit.LOGIN_IP, client_ip(request))
    await enforce_rate_limit(rate_limit.LOGIN_ACCOUNT, email or "<empty>")
    if not email or not password:
        raise AppError(401, INVALID_LOGIN, {"WWW-Authenticate": "Bearer"})
    user = await auth_service.authenticate_user(db, email, password)
    if user is None:
        raise AppError(401, INVALID_LOGIN, {"WWW-Authenticate": "Bearer"})
    return _token_for(user)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email, full_name=user.full_name)


@router.post("/logout", status_code=204)
async def logout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await auth_service.revoke_tokens(db, user.id)
