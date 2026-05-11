"""Request-id middleware (P10).

For every request it reads ``X-Request-ID`` from the client (or mints one as
a Snowflake rendered in hex with a ``req_`` prefix) and then:

* stores it in :data:`request_id_ctx` so any code in the request's task tree
  can read it without threading it through call signatures;
* binds it into ``structlog`` contextvars, so every log line emitted while
  the request is in flight carries ``request_id``;
* sets it as an attribute on the active OpenTelemetry server span — Tempo
  trace search and Loki log search then converge on the same id;
* keeps ``request.state.request_id`` populated for the docs/06 error envelope
  (see :func:`app.core.middleware.register_exception_handlers`);
* echoes it back as the ``X-Request-ID`` response header.

It runs *inside* the OpenTelemetry ASGI instrumentation (which has already
started the server span by the time a Starlette middleware executes), so
``trace.get_current_span()`` here returns that server span.
"""

from __future__ import annotations

import contextvars
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def current_request_id() -> str:
    """Return the request id bound to the current task, or ``""``."""
    return request_id_ctx.get()


def _mint_request_id() -> str:
    try:
        from app.core.ids import get_id_generator

        return f"req_{get_id_generator().next_id():x}"
    except Exception:  # noqa: BLE001 - never fail a request over id minting
        return f"req_{uuid.uuid4().hex[:16]}"


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or _mint_request_id()
        request.state.request_id = rid
        token = request_id_ctx.set(rid)
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span is not None:
                span.set_attribute("request_id", rid)
        except Exception:  # noqa: BLE001 - tracing must never break a request
            pass
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response
