"""OpenTelemetry wiring — traces export (OTLP/gRPC) + auto-instrumentation.

Shared by the FastAPI app and the background workers (each worker calls the
subset it needs). Everything here is defensive: a missing instrumentation
package downgrades to a no-op, so the service still boots without the full
observability stack installed.

Span topology we care about for one HTTP request that submits an answer::

    HTTP server span (FastAPIInstrumentor, carries the ``request_id`` attr)
      └─ SQLAlchemy SELECT/INSERT spans
      └─ Redis command spans
      └─ outbox.insert            ← custom, wraps the outbox row flush
            └─ SQLAlchemy INSERT
      └─ leaderboard.update       ← custom, wraps the ZADD + broadcast
            └─ Redis ZINCRBY / ZREVRANGE / ...

``request_id`` is set on the server span (see app.middleware.request_id) and
also emitted as a structlog field, so a Tempo trace search and a Loki log
search converge on the same id.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

log = logging.getLogger("app.telemetry")

_TRACING_READY = False


def init_tracing(
    *,
    service_name: str,
    service_version: str = "0.1.0",
    environment: str = "local",
    otlp_endpoint: str | None = None,
) -> None:
    """Install a global ``TracerProvider`` exporting via OTLP/gRPC.

    Resource attributes ``service.name`` / ``service.version`` /
    ``deployment.environment`` come from the caller (settings). Safe to call
    more than once — the second call is a no-op, since OpenTelemetry refuses
    to override an already-installed provider.
    """
    global _TRACING_READY
    if _TRACING_READY:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - optional dependency
        log.warning("telemetry: OpenTelemetry SDK unavailable (%s); tracing disabled", exc)
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = (
        OTLPSpanExporter(endpoint=otlp_endpoint) if otlp_endpoint else OTLPSpanExporter()
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _TRACING_READY = True
    log.info(
        "telemetry: tracing initialised service=%s env=%s endpoint=%s",
        service_name,
        environment,
        otlp_endpoint or "(default)",
    )


# ---------------------------------------------------------------------------
# Auto-instrumentation hooks. Each tolerates a missing package / double call.
# ---------------------------------------------------------------------------


def instrument_fastapi(app: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app, excluded_urls="metrics,/api/v1/health,/api/v1/ready"
        )
    except Exception as exc:  # noqa: BLE001 - instrumentation must never break the app
        log.warning("telemetry: FastAPI instrumentation skipped (%s)", exc)


def instrument_sqlalchemy(engine: Any) -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        # Async engines wrap a sync ``Engine``; the instrumentor hooks the
        # latter's ``connect`` events.
        sync_engine = getattr(engine, "sync_engine", engine)
        SQLAlchemyInstrumentor().instrument(engine=sync_engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry: SQLAlchemy instrumentation skipped (%s)", exc)


def instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry: Redis instrumentation skipped (%s)", exc)


def instrument_asyncpg() -> None:
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry: asyncpg instrumentation skipped (%s)", exc)


def instrument_aiokafka() -> None:
    try:
        from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor

        AIOKafkaInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry: aiokafka instrumentation skipped (%s)", exc)


# ---------------------------------------------------------------------------
# Helpers for custom spans / attributes
# ---------------------------------------------------------------------------


def get_tracer(name: str = "livequiz") -> Any | None:
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:  # pragma: no cover
        return None


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Start a child span if tracing is configured; a no-op otherwise.

    Usable from sync *or* async code — the OpenTelemetry span context
    manager itself never awaits, and span context propagates across
    ``await`` points via contextvars, so child spans created during awaits
    nest correctly under this one.
    """
    tracer = get_tracer()
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            with contextlib.suppress(Exception):
                current.set_attribute(key, value)
        yield


def set_current_span_attribute(key: str, value: Any) -> None:
    try:
        from opentelemetry import trace

        current = trace.get_current_span()
        if current is not None:
            current.set_attribute(key, value)
    except Exception:  # noqa: BLE001
        pass
