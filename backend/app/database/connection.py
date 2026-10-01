"""
Database connection with pgvector support
=========================================

- Normalises DATABASE_URL for asyncpg (Neon URLs carry ?sslmode=require, which
  asyncpg does not accept as a query parameter).
- TLS to the database is *verified* (certificate + hostname). Neon presents a
  publicly trusted certificate.
- Schema changes go through Alembic migrations (backend/migrations). Startup
  never creates or drops tables in production; see init_db().
"""
import logging
import ssl
from urllib.parse import parse_qs, urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

_SSL_MODES_REQUIRING_TLS = {"require", "verify-ca", "verify-full", "prefer"}


def _fix_database_url(url: str) -> tuple[str, dict]:
    """Return (asyncpg URL without query string, connect_args)."""
    parsed = urlparse(url)
    scheme = "postgresql+asyncpg"
    query = parse_qs(parsed.query or "")
    sslmode = (query.get("sslmode") or query.get("ssl") or [""])[0].lower()
    host = parsed.hostname or ""
    needs_ssl = sslmode in _SSL_MODES_REQUIRING_TLS or sslmode == "true" or host.endswith(".neon.tech")

    clean_url = urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))
    connect_args: dict = {}
    if needs_ssl:
        ctx = ssl.create_default_context()
        if not settings.DB_SSL_VERIFY:  # development escape hatch only; blocked in production
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx
    return clean_url, connect_args


db_url, connect_args = _fix_database_url(settings.DATABASE_URL)

engine = create_async_engine(
    db_url,
    echo=settings.DEBUG and not settings.is_production,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,  # Neon closes idle connections; avoid 500s after sleep
    pool_recycle=300,
    connect_args=connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Verify the database at startup. Never drops anything.

    Tables are created by `alembic upgrade head` (run by the Docker entrypoint).
    """
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        has_vector = (
            await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        ).scalar()
        if not has_vector:
            logger.error("pgvector extension is not installed; run `alembic upgrade head`.")


async def check_database() -> dict:
    """Readiness probe details (booleans only, nothing sensitive)."""
    result = {"database": False, "pgvector": False, "embedding_dimensions_ok": False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            result["database"] = True
            result["pgvector"] = bool(
                (await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))).scalar()
            )
            typmod = (
                await conn.execute(
                    text(
                        "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                        "JOIN pg_class c ON a.attrelid = c.oid "
                        "WHERE c.relname = 'chunks' AND a.attname = 'embedding' AND NOT a.attisdropped"
                    )
                )
            ).scalar()
            result["embedding_dimensions_ok"] = typmod == f"vector({settings.EMBEDDING_DIMENSIONS})"
    except Exception:
        logger.exception("Database readiness check failed")
    return result
