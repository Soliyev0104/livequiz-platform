"""Structured (JSON) logging via ``structlog``.

Every log line — emitted through ``structlog.get_logger()`` *or* through the
standard library (uvicorn, SQLAlchemy, ``logging.getLogger`` in our own
modules) — is rendered as a single JSON object with at least::

    {"timestamp": "...", "level": "info", "logger": "app.services.match",
     "service": "api-a", "message": "answer accepted",
     "request_id": "req_1a2b...", "trace_id": "...", "span_id": "..."}

``request_id`` is bound per request by :mod:`app.middleware.request_id` into
structlog's contextvars; ``trace_id`` / ``span_id`` are pulled from the
active OpenTelemetry span. Wiring lives in :func:`configure_logging`, called
once from ``app.main.create_app`` (and re-usable from worker entrypoints).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False
_HANDLER_NAME = "livequiz_json"


def _add_service_name(service: str):
    def _processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        return event_dict

    return _processor


def _add_otel_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Attach the active span's ``trace_id`` / ``span_id`` when one exists."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return event_dict
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is not None and ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(level: str = "INFO", *, service: str = "api") -> None:
    """Route both structlog and the stdlib logging tree through a JSON sink."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = getattr(logging, str(level).upper(), logging.INFO)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # Shared by structlog-native records and "foreign" stdlib records so the
    # JSON shape is identical regardless of where a line originated.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_service_name(service),
        _add_otel_context,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.set_name(_HANDLER_NAME)

    root = logging.getLogger()
    # Attach (don't clobber) so e.g. a test runner's capture handler survives.
    if not any(getattr(h, "name", None) == _HANDLER_NAME for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(log_level)

    # uvicorn / gunicorn install their own handlers with ``propagate=False``;
    # drop those so their lines flow through the root JSON handler instead of
    # being printed a second time in plain text.
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "gunicorn",
        "gunicorn.error",
        "gunicorn.access",
    ):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True

    # SQLAlchemy's engine echo is noisy at INFO; keep it quiet unless asked.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
