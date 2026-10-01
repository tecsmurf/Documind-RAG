"""
Pure-ASGI middleware (safe for SSE: nothing here buffers the response body).

- SecurityHeadersMiddleware: request id + security headers on every response.
- BodySizeLimitMiddleware: rejects oversized bodies *before* they are parsed or
  spooled to disk (Starlette's multipart parser would otherwise write the whole
  upload to a temp file before our handler can check its size).
"""
import json
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI (development only) loads its bundle from jsDelivr.
_DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request_id = secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope.get("path", "")
        csp = _DOCS_CSP if path in ("/docs", "/redoc") else _API_CSP

        async def send_wrapper(message: Message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"server"]
                existing = {k.lower() for k, _ in headers}

                def add(name: str, value: str):
                    if name.encode() not in existing:
                        headers.append((name.encode(), value.encode()))

                add("x-request-id", request_id)
                add("x-content-type-options", "nosniff")
                add("x-frame-options", "DENY")
                add("referrer-policy", "no-referrer")
                add("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=()")
                add("cross-origin-opener-policy", "same-origin")
                add("cross-origin-resource-policy", "cross-origin")
                add("content-security-policy", csp)
                add("cache-control", "no-store")
                if settings.is_production:
                    add("strict-transport-security", "max-age=31536000; includeSubDomains")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Per-route request body ceiling, enforced on Content-Length *and* on the stream."""

    DEFAULT_LIMIT = 64 * 1024  # JSON / form bodies

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _limit_for(path: str) -> int:
        if path.rstrip("/").endswith("/documents/upload"):
            # Allow multipart framing overhead on top of the file itself.
            return settings.max_file_size_bytes + 64 * 1024
        return BodySizeLimitMiddleware.DEFAULT_LIMIT

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        limit = self._limit_for(scope.get("path", ""))
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        return await _reject_too_large(send)
                except ValueError:
                    return await _reject(send, 400, "Invalid Content-Length.")

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message: Message):
            nonlocal response_started
            if too_large:
                # Whatever the app made of the aborted body (400/500), answer 413 instead.
                if not response_started:
                    response_started = True
                    await _reject_too_large(send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            pass
        if too_large and not response_started:
            await _reject_too_large(send)


class _BodyTooLarge(Exception):
    pass


async def _reject_too_large(send: Send):
    await _reject(send, 413, f"Request too large. Maximum file size is {settings.MAX_FILE_SIZE_MB} MB.")


async def _reject(send: Send, status: int, detail: str):
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
