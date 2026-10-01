"""Token bucket semantics, login limiting through the API, Redis backend."""
import asyncio
import shutil
import socket
import subprocess
import time

import pytest

from app.core.rate_limit import LOGIN_ACCOUNT, BucketPolicy, MemoryBucketStore, RedisBucketStore
from tests.helpers import register


async def test_bucket_capacity_and_refill():
    store = MemoryBucketStore()
    policy = BucketPolicy("t", 50, 1.2)
    t = 1000.0
    for i in range(50):
        d = await store.take("k", policy, now=t)
        assert d.allowed, i
    denied = await store.take("k", policy, now=t)
    assert not denied.allowed and denied.retry_after == 2  # ceil(1.2)
    assert not (await store.take("k", policy, now=t + 1.1)).allowed
    assert (await store.take("k", policy, now=t + 1.1 + 1.2)).allowed  # one token back after 1.2s
    assert not (await store.take("k", policy, now=t + 2.4)).allowed
    # 50 * 1.2 = 60 s later the bucket is full again, but never above capacity
    allowed = 0
    for _ in range(60):
        allowed += (await store.take("k", policy, now=t + 1000)).allowed
    assert allowed == 50
    assert (await store.take("other", policy, now=t)).allowed  # buckets are per key


async def test_memory_store_is_bounded():
    store = MemoryBucketStore(max_keys=100)
    policy = BucketPolicy("t", 1, 1.0)
    for i in range(1000):
        await store.take(f"k{i}", policy, now=0)
    assert len(store._buckets) == 100


@pytest.fixture
def frozen_clock(monkeypatch):
    """bcrypt makes 50 logins take seconds; freeze the limiter clock so no tokens refill mid-test."""
    import app.core.rate_limit as rl

    monkeypatch.setattr(rl, "_monotonic", lambda: 5000.0)


async def test_login_rate_limit_per_account(client, frozen_clock):
    assert LOGIN_ACCOUNT.capacity == 50 and LOGIN_ACCOUNT.refill_seconds == 1.2
    await register(client, "victim@example.com")
    codes = []
    for _ in range(51):
        r = await client.post("/api/auth/login", data={"username": "victim@example.com", "password": "bad guess"})
        codes.append(r.status_code)
    assert codes[:50] == [401] * 50
    assert codes[50] == 429
    assert int(r.headers["Retry-After"]) >= 1
    # Even the right password is refused while the bucket is empty (no bypass).
    r = await client.post("/api/auth/login", data={"username": "victim@example.com", "password": "correct horse battery"})
    assert r.status_code == 429
    # Case/whitespace variations hit the same bucket.
    r = await client.post("/api/auth/login", data={"username": " VICTIM@example.com", "password": "x"})
    assert r.status_code == 429


async def test_login_rate_limit_spoofed_forwarded_for(client, frozen_clock):
    """Rotating X-Forwarded-For does not reset the per-account bucket."""
    await register(client, "target@example.com")
    for i in range(50):
        await client.post("/api/auth/login", data={"username": "target@example.com", "password": "x"},
                          headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = await client.post("/api/auth/login", data={"username": "target@example.com", "password": "x"},
                          headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429


async def test_register_rate_limited(client):
    codes = []
    for i in range(7):
        r = await client.post("/api/auth/register",
                              json={"email": f"u{i}@example.com", "password": "password123", "full_name": "U"})
        codes.append(r.status_code)
    assert codes[:5] == [201] * 5 and codes[5] == 429


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def redis_url():
    if not shutil.which("redis-server"):
        pytest.skip("redis-server not installed")
    port = _free_port()
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL)
    time.sleep(0.5)
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait()


async def test_redis_bucket_is_atomic_and_shared(redis_url):
    a, b = RedisBucketStore(redis_url), RedisBucketStore(redis_url)  # two "workers"
    policy = BucketPolicy("rtest", 50, 1.2)
    now = time.time()
    results = await asyncio.gather(*[(a if i % 2 else b).take("acct", policy, now=now) for i in range(80)])
    assert sum(r.allowed for r in results) == 50  # no over-admission under concurrency
    denied = await a.take("acct", policy, now=now)
    assert not denied.allowed and denied.retry_after == 2
    assert (await b.take("acct", policy, now=now + 1.3)).allowed
