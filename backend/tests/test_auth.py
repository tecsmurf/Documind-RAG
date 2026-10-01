"""Authentication: registration, login, JWT validation, inactive users, logout."""
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import update

from app.core import security
from app.core.config import settings
from app.database.connection import async_session
from app.models import User
from tests.helpers import register


async def login(client, email, password):
    return await client.post("/api/auth/login", data={"username": email, "password": password})


async def test_register_login_me(client):
    headers = await register(client, "Alice@Example.com", name="Alice")
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == {"id": 1, "email": "alice@example.com", "full_name": "Alice"}  # normalised email

    r = await login(client, "ALICE@example.com ", "correct horse battery")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


async def test_register_validation(client):
    bad = [
        {"email": "not-an-email", "password": "longenough1", "full_name": "X"},
        {"email": "a@example.com", "password": "short", "full_name": "X"},
        {"email": "a@example.com", "password": "é" * 40, "full_name": "X"},  # 80 bytes > bcrypt limit
        {"email": "a@example.com", "password": "longenough1", "full_name": "\x00\x01"},
    ]
    for payload in bad:
        r = await client.post("/api/auth/register", json=payload)
        assert r.status_code == 422, payload
        assert "longenough1" not in r.text  # submitted values are not echoed back


async def test_duplicate_email_case_insensitive(client):
    await register(client, "bob@example.com")
    r = await client.post(
        "/api/auth/register", json={"email": "BOB@example.com", "password": "another password", "full_name": "B"}
    )
    assert r.status_code == 409


async def test_login_errors_are_generic(client):
    await register(client, "carol@example.com")
    wrong_pw = await login(client, "carol@example.com", "wrong password")
    no_user = await login(client, "nobody@example.com", "wrong password")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["detail"] == no_user.json()["detail"] == "Invalid email or password."


async def test_login_timing_does_not_reveal_accounts(client):
    await register(client, "dave@example.com")
    t0 = time.perf_counter()
    await login(client, "dave@example.com", "wrong password")
    known = time.perf_counter() - t0
    t0 = time.perf_counter()
    await login(client, "ghost@example.com", "wrong password")
    unknown = time.perf_counter() - t0
    # Both paths run one bcrypt check (~100ms+); unknown must not be dramatically faster.
    assert unknown > known * 0.5


async def test_inactive_user_cannot_login_and_token_rejected(client):
    headers = await register(client, "erin@example.com")
    async with async_session() as db:
        await db.execute(update(User).where(User.email == "erin@example.com").values(is_active=False))
        await db.commit()
    r = await login(client, "erin@example.com", "correct horse battery")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401


async def test_logout_revokes_tokens(client):
    headers = await register(client, "frank@example.com")
    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
    r = await login(client, "frank@example.com", "correct horse battery")
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/auth/me", headers=fresh)).status_code == 200


async def test_jwt_manipulation_rejected(client):
    await register(client, "gina@example.com")
    now = datetime.now(timezone.utc)
    base = {"sub": "1", "ver": 0, "type": "access", "iss": settings.JWT_ISSUER, "iat": now, "nbf": now,
            "exp": now + timedelta(minutes=5)}
    forged = [
        jwt.encode(base, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256"),
        jwt.encode({**base, "exp": now - timedelta(seconds=1)}, settings.SECRET_KEY, algorithm="HS256"),  # expired
        jwt.encode({**base, "iss": "someone-else"}, settings.SECRET_KEY, algorithm="HS256"),
        jwt.encode({**base, "type": "refresh"}, settings.SECRET_KEY, algorithm="HS256"),
        jwt.encode({k: v for k, v in base.items() if k != "ver"}, settings.SECRET_KEY, algorithm="HS256"),
        jwt.encode({**base, "sub": "2"}, settings.SECRET_KEY, algorithm="HS256"),  # user does not exist
        jwt.encode(base, settings.SECRET_KEY, algorithm="HS512"),  # algorithm not allowed
        jwt.encode(base, None, algorithm="none"),  # unsigned
        "not.a.jwt",
        "",
    ]
    for token in forged:
        r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, token
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers={"Authorization": "Basic abc"})).status_code == 401
    valid = jwt.encode(base, settings.SECRET_KEY, algorithm="HS256")
    assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {valid}"})).status_code == 200


def test_token_has_no_pii():
    payload = jwt.decode(security.create_access_token(7, 3), options={"verify_signature": False})
    assert payload["sub"] == "7" and payload["ver"] == 3 and "email" not in payload


def test_password_hashing_compat_and_malformed_hashes():
    legacy = bcrypt.hashpw(b"old-password", bcrypt.gensalt(rounds=4)).decode()  # passlib stored $2b$ hashes
    assert security.verify_password("old-password", legacy)
    assert not security.verify_password("nope", legacy)
    for broken in ["", "not-a-hash", "$2b$12$short", None]:
        assert security.verify_password("anything", broken) is False
    h = security.hash_password("a" * 72)
    assert security.verify_password("a" * 72, h)


async def test_sql_injection_in_login_is_inert(client):
    await register(client, "hank@example.com")
    for email in ["' OR '1'='1", "hank@example.com' --", "x\"; DROP TABLE users; --"]:
        r = await login(client, email, "' OR '1'='1")
        assert r.status_code == 401
    assert (await login(client, "hank@example.com", "correct horse battery")).status_code == 200
