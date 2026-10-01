"""Alembic environment: async engine built from the app's own (TLS-verified) settings."""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.connection import Base, connect_args, db_url
import app.models  # noqa: F401  (register models on Base.metadata)

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(db_url, connect_args=connect_args)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=db_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async_migrations())
