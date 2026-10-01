"""
Test setup: real PostgreSQL + pgvector (TEST_DATABASE_URL, a database whose
name ends in _test), schema built by the real Alembic migrations, Gemini
replaced by a deterministic fake. Nothing here can touch production.
"""
import os

os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/documind_test"
)
os.environ["GOOGLE_API_KEY"] = "test-key-not-real"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-123456"
os.environ.pop("REDIS_URL", None)
os.environ.pop("RENDER", None)

import asyncio  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

assert os.environ["DATABASE_URL"].rsplit("/", 1)[-1].endswith("_test"), "tests only run against *_test databases"

from app.core.rate_limit import limiter  # noqa: E402
from app.database.connection import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import gemini  # noqa: E402
from tests.helpers import fake_vector  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _reset_schema_and_migrate():
    import asyncpg

    async def reset():
        url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
        conn = await asyncpg.connect(url)
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()

    asyncio.run(reset())
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, env=os.environ.copy())


_reset_schema_and_migrate()


class FakeGemini:
    def __init__(self):
        self.reset()

    def reset(self):
        self.embed_error = None
        self.generate_error = None
        self.answer_parts = ["The answer ", "is in ", "the document [1]."]
        self.embed_calls = []
        self.generate_calls = []
        self.delay = 0.0

    async def embed_texts(self, texts, task_type):
        self.embed_calls.append((list(texts), task_type))
        if self.embed_error:
            raise self.embed_error
        return [fake_vector(t) for t in texts]

    async def stream_generate(self, system_instruction, contents):
        self.generate_calls.append((system_instruction, contents))
        if self.generate_error and not self.answer_parts:
            raise self.generate_error
        for part in self.answer_parts:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield part
        if self.generate_error:
            raise self.generate_error


@pytest.fixture
def fake_gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(gemini, "embed_texts", fake.embed_texts)
    monkeypatch.setattr(gemini, "stream_generate", fake.stream_generate)
    return fake


@pytest.fixture(autouse=True)
async def clean_state(fake_gemini):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, documents, chunks, conversations, messages RESTART IDENTITY CASCADE"))
    await limiter.reset()
    yield


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
