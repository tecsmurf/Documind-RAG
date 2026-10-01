"""
Safe error responses.

Clients only ever see short, generic messages plus a request id. Full details
(tracebacks, SQL, provider errors) go to the server log, which never contains
secrets because settings are not logged and provider errors are summarised.
"""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("documind.errors")


class AppError(Exception):
    """An expected failure with a message that is safe to show users."""

    def __init__(self, status_code: int, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.headers = headers


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _body(detail, request: Request) -> dict:
    body = {"detail": detail}
    rid = _request_id(request)
    if rid:
        body["request_id"] = rid
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(_body(exc.message, request), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(_body(detail, request), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Report which fields failed without echoing the submitted values back.
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body", "message": e.get("msg", "Invalid value")}
            for e in exc.errors()
        ]
        body = _body("Invalid request.", request)
        body["errors"] = errors[:20]
        return JSONResponse(body, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s (request_id=%s)", request.method, request.url.path, _request_id(request))
        return JSONResponse(_body("Something went wrong. Please try again.", request), status_code=500)
