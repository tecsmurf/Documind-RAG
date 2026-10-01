"""
Application settings
====================

Environment-aware configuration (development / testing / production).

Production refuses to start when it is misconfigured: weak or default
SECRET_KEY, DEBUG enabled, missing GOOGLE_API_KEY / DATABASE_URL, or no exact
ALLOWED_ORIGINS. Errors name the offending variable but never print its value.
"""
import os
from functools import cached_property
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known placeholder/default secrets that must never be used in production.
_WEAK_SECRETS = {
    "",
    "dev-secret-key-change-in-production",
    "docker-dev-secret",
    "random-string",
    "secret",
    "changeme",
    "change-me",
    "your-secret-key",
}
_MIN_SECRET_LENGTH = 32

_DEV_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:\d+)?"


def _default_environment() -> str:
    # Render sets RENDER=true on every service. Defaulting to production there
    # means a forgotten ENVIRONMENT variable fails closed, not open.
    return "production" if os.getenv("RENDER") else "development"


class ConfigError(RuntimeError):
    """Raised at startup when configuration is unsafe or incomplete."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    APP_NAME: str = "DocuMind"
    ENVIRONMENT: Literal["development", "testing", "production"] = Field(default_factory=_default_environment)
    DEBUG: bool = False

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=5, le=60 * 24 * 7)
    JWT_ISSUER: str = "documind"

    # Database (PostgreSQL with pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/doc_intelligence"
    DB_SSL_VERIFY: bool = True
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # Google Gemini (server-side only, never sent to the browser)
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIMENSIONS: int = 3072  # gemini-embedding-001 default output size
    EMBEDDING_BATCH_SIZE: int = Field(default=50, ge=1, le=100)
    GEMINI_TIMEOUT_SECONDS: float = 60.0
    GEMINI_MAX_RETRIES: int = Field(default=3, ge=0, le=6)
    GEMINI_MAX_OUTPUT_TOKENS: int = 2048

    # RAG
    CHUNK_SIZE: int = Field(default=1200, ge=200, le=8000)  # characters
    CHUNK_OVERLAP: int = Field(default=150, ge=0, le=2000)  # characters
    TOP_K: int = Field(default=5, ge=1, le=20)
    MAX_CONTEXT_CHARS: int = 16000
    MAX_HISTORY_MESSAGES: int = 10
    MAX_HISTORY_CHARS: int = 8000
    MAX_QUESTION_CHARS: int = 2000
    CHAT_TIMEOUT_SECONDS: float = 120.0

    # Upload / processing limits (Render free tier has 512 MB RAM)
    MAX_FILE_SIZE_MB: int = Field(default=10, ge=1, le=100)
    MAX_PDF_PAGES: int = 500
    MAX_EXTRACTED_CHARS: int = 2_000_000
    MAX_CHUNKS_PER_DOCUMENT: int = 1500
    MAX_DOCUMENTS_PER_USER: int = 50
    PROCESSING_TIMEOUT_SECONDS: float = 600.0
    MAX_CONCURRENT_INGESTIONS: int = 2

    # CORS: comma-separated exact origins, e.g. https://documind.vercel.app
    ALLOWED_ORIGINS: str = ""

    # Rate limiting. REDIS_URL switches to a shared Redis bucket store.
    REDIS_URL: str = ""
    WEB_CONCURRENCY: int = 1
    TRUSTED_PROXY_HOPS: int = Field(default=1, ge=0, le=5)
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_CAPACITY: int = 50
    LOGIN_RATE_REFILL_SECONDS: float = 1.2
    LOGIN_IP_RATE_CAPACITY: int = 100
    LOGIN_IP_RATE_REFILL_SECONDS: float = 1.2
    REGISTER_RATE_CAPACITY: int = 5
    REGISTER_RATE_REFILL_SECONDS: float = 720.0  # 5 per hour per IP
    UPLOAD_RATE_CAPACITY: int = 10
    UPLOAD_RATE_REFILL_SECONDS: float = 120.0  # ~30 per hour per user
    CHAT_RATE_CAPACITY: int = 20
    CHAT_RATE_REFILL_SECONDS: float = 6.0  # 10 per minute sustained
    CONVERSATION_RATE_CAPACITY: int = 30
    CONVERSATION_RATE_REFILL_SECONDS: float = 10.0

    @field_validator("DATABASE_URL", "SECRET_KEY", "GOOGLE_API_KEY", "ALLOWED_ORIGINS", "REDIS_URL")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @cached_property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_origin_regex(self) -> str | None:
        # Localhost is only trusted outside production.
        return None if self.is_production else _DEV_ORIGIN_REGEX

    def validate_for_startup(self) -> None:
        """Fail fast on unsafe configuration. Never includes secret values."""
        problems: list[str] = []
        if self.is_production:
            if self.DEBUG:
                problems.append("DEBUG must be false in production.")
            if self.SECRET_KEY in _WEAK_SECRETS or len(self.SECRET_KEY) < _MIN_SECRET_LENGTH:
                problems.append(
                    f"SECRET_KEY is missing, a known default, or shorter than {_MIN_SECRET_LENGTH} characters. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            if not self.GOOGLE_API_KEY:
                problems.append("GOOGLE_API_KEY is required in production.")
            if not os.getenv("DATABASE_URL"):
                problems.append("DATABASE_URL must be set explicitly in production.")
            if not self.allowed_origins:
                problems.append("ALLOWED_ORIGINS must list the exact frontend origin(s) in production.")
            for origin in self.allowed_origins:
                if "*" in origin or not origin.startswith("https://"):
                    problems.append("ALLOWED_ORIGINS entries must be exact https:// origins (no wildcards).")
                    break
            if self.WEB_CONCURRENCY > 1 and not self.REDIS_URL:
                problems.append(
                    "WEB_CONCURRENCY > 1 needs REDIS_URL so rate limits are shared between workers."
                )
            if not self.DB_SSL_VERIFY:
                problems.append("DB_SSL_VERIFY must stay enabled in production.")
        if self.CHUNK_OVERLAP >= self.CHUNK_SIZE:
            problems.append("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        if problems:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))


settings = Settings()
