"""
Token-bucket rate limiting
==========================

Each key owns a bucket of ``capacity`` tokens. Every request takes one token;
tokens come back continuously at one per ``refill_seconds``. Example for login:
capacity 50, refill 1.2 s → 50 quick attempts, then one attempt per 1.2 s.

Backends
--------
- ``MemoryBucketStore``: per-process, bounded (LRU-evicted) so many distinct keys
  cannot exhaust memory. Correct for the current deployment: one Render instance
  running one uvicorn worker.
- ``RedisBucketStore``: shared across workers/instances. The whole
  read-refill-take-write cycle runs in one Lua script, so it is atomic.
  Enabled by setting REDIS_URL. Production refuses to start with
  WEB_CONCURRENCY > 1 and no REDIS_URL (see config.validate_for_startup).
"""
import asyncio
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


def _monotonic() -> float:
    return time.monotonic()


@dataclass(frozen=True)
class BucketPolicy:
    name: str
    capacity: int
    refill_seconds: float  # seconds per regained token


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int  # whole seconds until one token is available (0 if allowed)


class MemoryBucketStore:
    def __init__(self, max_keys: int = 50_000):
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def take(self, key: str, policy: BucketPolicy, now: float | None = None) -> RateDecision:
        now = _monotonic() if now is None else now
        async with self._lock:
            tokens, updated = self._buckets.get(key, (float(policy.capacity), now))
            tokens = min(policy.capacity, tokens + max(0.0, now - updated) / policy.refill_seconds)
            if tokens >= 1:
                tokens -= 1
                allowed, retry = True, 0
            else:
                allowed = False
                retry = math.ceil((1 - tokens) * policy.refill_seconds)
            self._buckets[key] = (tokens, now)
            self._buckets.move_to_end(key)
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
            return RateDecision(allowed, int(tokens), retry)

    async def reset(self) -> None:
        async with self._lock:
            self._buckets.clear()


_LUA_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + math.max(0, now - ts) / refill)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = math.ceil((1 - tokens) * refill)
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', key, math.ceil(capacity * refill) + 60)
return {allowed, math.floor(tokens), retry}
"""


class RedisBucketStore:
    def __init__(self, url: str):
        import redis.asyncio as redis  # imported lazily; optional dependency at runtime

        self._redis = redis.from_url(url, decode_responses=True)
        self._script = self._redis.register_script(_LUA_TOKEN_BUCKET)

    async def take(self, key: str, policy: BucketPolicy, now: float | None = None) -> RateDecision:
        # Wall clock (not monotonic) so every instance shares one timeline.
        now = time.time() if now is None else now
        allowed, remaining, retry = await self._script(
            keys=[f"rl:{key}"], args=[policy.capacity, policy.refill_seconds, now]
        )
        return RateDecision(bool(int(allowed)), int(remaining), int(retry))

    async def reset(self) -> None:  # pragma: no cover - only used by tests on memory store
        pass


class RateLimiter:
    def __init__(self):
        self._store = None
        self._fallback = MemoryBucketStore()

    @property
    def store(self):
        if self._store is None:
            if settings.REDIS_URL:
                self._store = RedisBucketStore(settings.REDIS_URL)
                logger.info("Rate limiter: Redis backend")
            else:
                self._store = MemoryBucketStore()
                logger.info("Rate limiter: in-memory backend (single worker)")
        return self._store

    async def hit(self, policy: BucketPolicy, identity: str) -> RateDecision:
        if not settings.RATE_LIMIT_ENABLED:
            return RateDecision(True, policy.capacity, 0)
        try:
            return await self.store.take(f"{policy.name}:{identity}", policy)
        except Exception:
            # Redis outage: keep limiting per process rather than failing open.
            logger.exception("Rate limiter backend failed; using in-process fallback")
            return await self._fallback.take(f"{policy.name}:{identity}", policy)

    async def reset(self) -> None:
        if self._store is not None:
            await self._store.reset()
        await self._fallback.reset()


limiter = RateLimiter()

LOGIN_ACCOUNT = BucketPolicy("login-acct", settings.LOGIN_RATE_CAPACITY, settings.LOGIN_RATE_REFILL_SECONDS)
LOGIN_IP = BucketPolicy("login-ip", settings.LOGIN_IP_RATE_CAPACITY, settings.LOGIN_IP_RATE_REFILL_SECONDS)
REGISTER_IP = BucketPolicy("register-ip", settings.REGISTER_RATE_CAPACITY, settings.REGISTER_RATE_REFILL_SECONDS)
UPLOAD_USER = BucketPolicy("upload", settings.UPLOAD_RATE_CAPACITY, settings.UPLOAD_RATE_REFILL_SECONDS)
CHAT_USER = BucketPolicy("chat", settings.CHAT_RATE_CAPACITY, settings.CHAT_RATE_REFILL_SECONDS)
CONVERSATION_USER = BucketPolicy(
    "conversation", settings.CONVERSATION_RATE_CAPACITY, settings.CONVERSATION_RATE_REFILL_SECONDS
)
