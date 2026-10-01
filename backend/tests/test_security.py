"""Config hardening, CORS, headers, body limits, error hygiene, Gemini error mapping, migrations."""
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.core.config import ConfigError, Settings
from app.services import gemini
from tests.helpers import register

BACKEND = Path(__file__).resolve().parents[1]

GOOD_PROD = dict(
    ENVIRONMENT="production", DEBUG=False, SECRET_KEY="x" * 48, GOOGLE_API_KEY="k",
    ALLOWED_ORIGINS="https://documind.vercel.app",
)


def prod(monkeypatch, **overrides):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db.neon.tech/x")
    return Settings(**{**GOOD_PROD, **overrides})


def test_production_config_validation(monkeypatch):
    prod(monkeypatch).validate_for_startup()  # good config passes
    bad = [
        {"DEBUG": True},
        {"SECRET_KEY": "dev-secret-key-change-in-production"},
        {"SECRET_KEY": "random-string"},
        {"SECRET_KEY": "short"},
        {"GOOGLE_API_KEY": ""},
        {"ALLOWED_ORIGINS": ""},
        {"ALLOWED_ORIGINS": "https://*.vercel.app"},
        {"ALLOWED_ORIGINS": "http://documind.vercel.app"},
        {"WEB_CONCURRENCY": 4},
        {"DB_SSL_VERIFY": False},
    ]
    for override in bad:
        with pytest.raises(ConfigError) as exc:
            prod(monkeypatch, **override).validate_for_startup()
        msg = str(exc.value)
        assert "x" * 48 not in msg and "neon.tech" not in msg  # never prints secrets
    prod(monkeypatch, WEB_CONCURRENCY=4, REDIS_URL="redis://r:6379").validate_for_startup()


def test_render_defaults_to_production(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert Settings().ENVIRONMENT == "production"
    monkeypatch.delenv("RENDER")
    assert Settings().ENVIRONMENT == "development"


def test_production_app_refuses_to_boot_with_defaults():
    env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "GOOGLE_API_KEY")}
    env.update(ENVIRONMENT="production", ALLOWED_ORIGINS="https://documind.vercel.app")
    code = "import asyncio; from app.main import app, lifespan\nasync def m():\n  async with lifespan(app): pass\nasyncio.run(m())"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "SECRET_KEY" in r.stderr and "GOOGLE_API_KEY" in r.stderr


def test_production_disables_docs_and_localhost_cors():
    env = {**os.environ, "ENVIRONMENT": "production", "ALLOWED_ORIGINS": "https://documind.vercel.app"}
    code = (
        "import httpx, asyncio\nfrom app.main import create_app\napp = create_app()\n"
        "async def m():\n"
        "  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://t') as c:\n"
        "    print((await c.get('/docs')).status_code, (await c.get('/openapi.json')).status_code)\n"
        "    for o in ['https://documind.vercel.app', 'https://evil.vercel.app', 'http://localhost:5173']:\n"
        "      r = await c.options('/api/health', headers={'Origin': o, 'Access-Control-Request-Method': 'GET'})\n"
        "      print(o, r.headers.get('access-control-allow-origin'))\n"
        "    print((await c.get('/api/health')).headers.get('strict-transport-security'))\n"
        "asyncio.run(m())"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[0] == "404 404"
    assert lines[1].endswith("https://documind.vercel.app")
    assert lines[2].endswith("None") and lines[3].endswith("None")
    assert "max-age" in lines[4]


async def test_cors_in_development(client):
    ok = await client.options("/api/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert ok.headers.get("access-control-allow-credentials") is None
    for evil in ["https://attacker.vercel.app", "https://evil.onrender.com", "http://localhost.evil.com", "null"]:
        r = await client.options("/api/auth/login", headers={"Origin": evil, "Access-Control-Request-Method": "POST"})
        assert r.headers.get("access-control-allow-origin") is None, evil


async def test_security_headers(client):
    r = await client.get("/api/health")
    for header in ["x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy",
                   "permissions-policy", "x-request-id"]:
        assert header in r.headers
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in r.headers


async def test_json_body_size_limit(client):
    r = await client.post("/api/auth/register", content=b"{" + b" " * 200_000 + b"}",
                          headers={"content-type": "application/json"})
    assert r.status_code == 413


async def test_chunked_upload_without_content_length_is_capped(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    h = await register(client, "big@example.com")

    async def body():
        yield b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n\r\n"
        for _ in range(40):
            yield b"a" * 65536
        yield b"\r\n--b--\r\n"

    r = await client.post("/api/documents/upload", headers={**h, "content-type": "multipart/form-data; boundary=b"},
                          content=body())
    assert r.status_code == 413


async def test_validation_errors_do_not_echo_input(client):
    r = await client.post("/api/auth/register", json={"email": "<script>alert(1)</script>", "password": "p", "full_name": "x"})
    assert r.status_code == 422 and "<script>" not in r.text


async def test_readiness_endpoint(client):
    r = await client.get("/api/health/ready")
    body = r.json()
    assert r.status_code == 200, body
    assert body["checks"] == {"database": True, "pgvector": True, "embedding_dimensions_ok": True, "gemini_configured": True}


def test_gemini_error_mapping_is_safe():
    from google.genai import errors

    def api_error(code, status, message):
        return errors.ClientError(code, {"error": {"code": code, "status": status, "message": message}})

    cases = {
        (429, "RESOURCE_EXHAUSTED", "Quota exceeded for project 123"): "quota",
        (400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."): "auth",
        (403, "PERMISSION_DENIED", "denied"): "auth",
        (404, "NOT_FOUND", "models/gemini-2.0-flash is not found"): "model_unavailable",
    }
    for (code, status, message), kind in cases.items():
        err = gemini.map_exception(api_error(code, status, message))
        assert err.kind == kind
        assert message not in err.user_message and "project 123" not in err.user_message
    assert gemini.map_exception(TimeoutError()).kind == "timeout"
    assert gemini.map_exception(errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "x"}})).kind == "model_unavailable"


async def test_missing_api_key_is_a_clean_error(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(gemini, "_client", None)
    with pytest.raises(gemini.GeminiError) as exc:
        gemini.get_client()
    assert exc.value.kind == "not_configured"


def test_frontend_never_references_gemini_key():
    frontend = BACKEND.parent / "frontend"
    hits = []
    for path in list((frontend / "src").rglob("*")) + [frontend / "index.html", frontend / "vite.config.js"]:
        if path.is_file() and path.suffix in (".js", ".jsx", ".html", ".css", ".json"):
            text = path.read_text(errors="ignore")
            if "GOOGLE_API_KEY" in text or "generativelanguage" in text or "AIza" in text:
                hits.append(str(path))
    assert hits == []


def test_migrations_preserve_legacy_data():
    """Baseline → insert legacy rows (old shape) → upgrade → data intact, new columns defaulted."""
    import asyncio
    import asyncpg

    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)[0] + "/documind_migration_test"
    admin = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")

    async def prepare():
        conn = await asyncpg.connect(admin)
        await conn.execute("DROP DATABASE IF EXISTS documind_migration_test")
        await conn.execute("CREATE DATABASE documind_migration_test")
        await conn.close()

    asyncio.run(prepare())
    env = {**os.environ, "DATABASE_URL": url.replace("postgresql", "postgresql+asyncpg", 1)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=BACKEND, env=env, check=True, capture_output=True)
    run("upgrade", "0001_baseline")

    async def seed_and_check(phase):
        conn = await asyncpg.connect(url)
        if phase == "seed":
            await conn.execute("INSERT INTO users (email, full_name, hashed_password, created_at) VALUES ('old@x.io','Old','$2b$12$x', now())")
            await conn.execute("INSERT INTO documents (user_id, filename, file_type, file_size, total_chunks, status, error_message, created_at) VALUES (1,'a.pdf','pdf',1,0,'error','Error code: 429 - credit_balance_exhausted', now()), (1,'b.txt','txt',1,0,'processing',NULL, now())")
            await conn.execute("INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (1,'c',now(),now())")
            await conn.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (1,'user','hi',now())")
        else:
            user = await conn.fetchrow("SELECT email, is_active, token_version FROM users")
            assert tuple(user) == ("old@x.io", True, 0)
            docs = await conn.fetch("SELECT status, error_message, updated_at FROM documents ORDER BY id")
            assert [d["status"] for d in docs] == ["error", "error"]
            assert "429" not in docs[0]["error_message"] and all(d["updated_at"] for d in docs)
            assert await conn.fetchval("SELECT status FROM messages") == "complete"
            # cascade now enforced by the database
            await conn.execute("DELETE FROM users")
            assert await conn.fetchval("SELECT count(*) FROM messages") == 0
        await conn.close()

    asyncio.run(seed_and_check("seed"))
    run("upgrade", "head")
    asyncio.run(seed_and_check("check"))
    run("upgrade", "head")  # idempotent re-run
