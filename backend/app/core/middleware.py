"""Global exception handlers — the docs/06 error envelope.

``register_exception_handlers`` converts ``AuthError`` and Pydantic
validation failures into the documented envelope; anything else lands on a
500 with code ``INTERNAL_ERROR``. The per-request ``request_id`` it embeds is
set by :class:`app.middleware.request_id.RequestIDMiddleware`.

Error envelope (per docs/06)::

    {
      "error": {"code": "...", "message": "...", "details": {...}},
      "request_id": "req_..."
    }
"""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.security import AuthError

log = logging.getLogger("app.errors")


_DEFAULT_MESSAGES: dict[str, str] = {
    "AUTH_REQUIRED": "Authentication required.",
    "FORBIDDEN": "You do not have permission to perform this action.",
    "RATE_LIMITED": "Too many requests.",
    "VALIDATION_ERROR": "Request payload is invalid.",
    "INTERNAL_ERROR": "Internal server error.",
}


def _envelope(
    *,
    code: str,
    http_status: int,
    request: Request,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message or _DEFAULT_MESSAGES.get(code, ""),
            "details": details or {},
        },
        "request_id": getattr(request.state, "request_id", None),
    }
    headers: dict[str, str] | None = None
    retry_after_ms = (details or {}).get("retry_after_ms")
    if code == "RATE_LIMITED" and isinstance(retry_after_ms, int | float) and retry_after_ms > 0:
        headers = {"Retry-After": str(math.ceil(retry_after_ms / 1000))}
    return JSONResponse(body, status_code=http_status, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return _envelope(
            code=exc.code,
            http_status=exc.http_status,
            request=request,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic errors include non-JSON-serializable values (e.g. bytes
        # context in ValueError); coerce via str() to keep the envelope safe.
        safe_errors = []
        for err in exc.errors():
            safe_errors.append(
                {
                    "loc": [str(p) for p in err.get("loc", ())],
                    "msg": err.get("msg"),
                    "type": err.get("type"),
                }
            )
        return _envelope(
            code="VALIDATION_ERROR",
            http_status=422,
            request=request,
            details={"errors": safe_errors},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled exception", exc_info=exc)
        return _envelope(
            code="INTERNAL_ERROR",
            http_status=500,
            request=request,
        )
