"""
Database Connection with pgvector support
==========================================

pgvector adds vector column type to PostgreSQL for similarity search.
This is how we store and search document embeddings.

Includes URL fixer for Neon/hosted PostgreSQL (same pattern as Project 1).
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from urllib.parse import urlparse, urlunparse

from app.core.config import settings


def _fix_database_url(url: str) -> dict:
    """
    Fix DATABASE_URL for asyncpg compatibility.
    - Strips query params (sslmode, channel_binding) that asyncpg doesn't accept
    - Converts postgres:// to postgresql+asyncpg://
    - Returns (url, connect_args) tuple
    """
    parsed = urlparse(url)

    # Fix scheme
    scheme = parsed.scheme
    if scheme == "postgres":
        scheme = "postgresql+asyncpg"
    elif scheme == "postgresql":
        scheme = "postgresql+asyncpg"
    elif "asyncpg" not in scheme:
        scheme = "postgresql+asyncpg"

    # Detect SSL need
    needs_ssl = "sslmode" in (parsed.query or "") or "neon" in (parsed.hostname or "")

    # Strip query params
    clean_url = urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))

    connect_args = {}
    if needs_ssl:
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    return clean_url, connect_args


db_url, connect_args = _fix_database_url(settings.DATABASE_URL)

engine = create_async_engine(
    db_url,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
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


async def init_db():
    """Create pgvector extension and all tables.
    
    NOTE: We drop and recreate tables to handle the vector dimension change
    from 1536 (OpenAI) to 3072 (Gemini). In production, use Alembic migrations.
    """
    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Drop existing tables to handle vector dimension change
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
