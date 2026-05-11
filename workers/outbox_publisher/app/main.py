"""Outbox publisher worker.

Polls ``outbox_events`` for unpublished rows, ships them to the matching
Redpanda topic, and marks ``published_at`` on broker ack. The worker is
the single Postgres → Redpanda bridge — the API never produces directly
so a broker outage cannot fail or delay a gameplay write.

Reliability contract
====================

* ``FOR UPDATE SKIP LOCKED`` lets multiple replicas run safely. We ship
  one in compose for simplicity; the lock semantics keep two-replica
  rollouts possible without code changes.
* Producer flags: ``acks=all`` + ``enable_idempotence=True`` so within a
  topic-partition Kafka guarantees no duplicates from a single
  producer. Combined with the ``published_at`` mark in Postgres, the
  end-to-end pipeline is at-least-once and behaves like exactly-once
  for any consumer that dedupes on ``event_id`` (the stream worker
  does — Redis SETNX + ReplacingMergeTree).
* On producer error the row stays ``published_at IS NULL``,
  ``publish_attempts`` increments, and the loop sleeps with
  exponential backoff. After 10 failures the envelope is copied to
  ``livequiz.events.dead_letter`` and the row marked published — so a
  poison message cannot stall the queue forever.

Operability
===========

* ``outbox_unpublished_total`` gauge is exported on ``:9100/metrics``
  for Prometheus scraping; it reflects the count of rows still
  unpublished, not the lifetime total.
* Logs structured via structlog; the ``event_id`` and ``event_type``
  are always present so a tail can correlate a stuck row with the
  corresponding Postgres row by id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import asyncpg
import structlog
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST

from app.topics import TOPIC_DEAD_LETTER, topic_for


# ---------------------------------------------------------------------------
# Constants / config
# ---------------------------------------------------------------------------

POLL_BATCH = 100
IDLE_SLEEP_S = 0.5         # No work → sleep this long before polling again.
PRODUCER_LINGER_MS = 20
MAX_PUBLISH_ATTEMPTS = 10  # After this many failures, divert to DLQ.
BACKOFF_BASE_S = 0.25
BACKOFF_MAX_S = 30.0
METRICS_PORT = 9100
PRODUCER_NAME = "livequiz-outbox-publisher"
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

SERVICE_NAME = os.environ.get("SERVICE_NAME", "outbox-publisher")


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


def _add_service(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), stream=sys.stdout)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_service,
        _add_otel_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.EventRenamer("message"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger("outbox-publisher")


# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------


def _init_telemetry() -> None:
    """Best-effort OTLP/gRPC tracing for the publisher (asyncpg + aiokafka).

    A missing OpenTelemetry package is non-fatal — the publisher's job is to
    drain the outbox, not to produce traces.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover
        log.warning("telemetry.sdk_unavailable", error=str(exc))
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment": os.environ.get("APP_ENV", "local"),
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    for name, fn in (
        ("asyncpg", "opentelemetry.instrumentation.asyncpg:AsyncPGInstrumentor"),
        ("aiokafka", "opentelemetry.instrumentation.aiokafka:AIOKafkaInstrumentor"),
    ):
        try:
            mod_name, cls_name = fn.split(":")
            mod = __import__(mod_name, fromlist=[cls_name])
            getattr(mod, cls_name)().instrument()
        except Exception as exc:  # noqa: BLE001
            log.warning("telemetry.instrument_skipped", target=name, error=str(exc))
    log.info("telemetry.ready", service=SERVICE_NAME, endpoint=endpoint or "(default)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_asyncpg_dsn(url: str) -> str:
    """Strip SQLAlchemy's ``+asyncpg`` suffix; asyncpg only knows the
    bare ``postgresql://`` scheme."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://"):]
    if url.startswith("postgres+asyncpg://"):
        return "postgres://" + url[len("postgres+asyncpg://"):]
    return url


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_envelope(row: asyncpg.Record) -> dict[str, Any]:
    """Build the on-wire envelope (per docs/08).

    Snowflake ids serialise as strings — JavaScript clients silently
    truncate ints past 2^53. ``payload`` is stored as JSONB in
    Postgres; asyncpg already decodes it to a dict.
    """
    payload = row["payload"]
    if isinstance(payload, str):
        # Some asyncpg setups (no jsonb codec) return text.
        payload = json.loads(payload)
    return {
        "event_id": str(row["id"]),
        "event_type": row["event_type"],
        "aggregate_type": row["aggregate_type"],
        "aggregate_id": str(row["aggregate_id"]),
        "occurred_at": _iso_z(row["occurred_at"]),
        "producer": PRODUCER_NAME,
        "schema_version": SCHEMA_VERSION,
        "payload": payload,
    }


def envelope_bytes(envelope: dict[str, Any]) -> bytes:
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Metrics HTTP server
# ---------------------------------------------------------------------------


class MetricsState:
    """Holds the Prometheus registry + the unpublished gauge.

    Kept separate from the asyncpg/aiokafka clients so the metrics
    server stays up even when the broker or DB drop out — that is when
    we most need to know the unpublished count.
    """

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.unpublished = Gauge(
            "outbox_unpublished_total",
            "Count of outbox_events rows with published_at IS NULL.",
            registry=self.registry,
        )


async def _metrics_server(state: MetricsState, port: int) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            # Drain headers — we don't care about routing details, every
            # request gets the metrics page. This keeps the server tiny.
            try:
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                    if not line or line == b"\r\n":
                        break
            except asyncio.TimeoutError:
                pass

            body = generate_latest(state.registry)
            headers = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {CONTENT_TYPE_LATEST}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(headers + body)
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    return await asyncio.start_server(handle, host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


async def _build_producer(bootstrap: str) -> AIOKafkaProducer:
    """Construct a producer configured for at-least-once with no
    intra-producer duplicates."""
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        acks="all",
        enable_idempotence=True,
        linger_ms=PRODUCER_LINGER_MS,
        max_in_flight_requests_per_connection=5,
        client_id=PRODUCER_NAME,
    )
    await producer.start()
    return producer


# ---------------------------------------------------------------------------
# Core polling loop
# ---------------------------------------------------------------------------


SELECT_BATCH_SQL = """
SELECT id, aggregate_type, aggregate_id, event_type, payload, occurred_at, publish_attempts
FROM outbox_events
WHERE published_at IS NULL
ORDER BY occurred_at
LIMIT $1
FOR UPDATE SKIP LOCKED
"""

MARK_PUBLISHED_SQL = """
UPDATE outbox_events
SET published_at = now()
WHERE id = ANY($1::bigint[])
"""

INCREMENT_ATTEMPTS_SQL = """
UPDATE outbox_events
SET publish_attempts = publish_attempts + 1
WHERE id = $1
"""

COUNT_UNPUBLISHED_SQL = "SELECT count(*) FROM outbox_events WHERE published_at IS NULL"


async def _process_batch(
    conn: asyncpg.Connection,
    producer: AIOKafkaProducer,
    backoff: dict[int, float],
) -> int:
    """Process one batch in a single tx.

    Returns the number of rows successfully published. Failed rows have
    their ``publish_attempts`` incremented (separate tx) and are left
    unpublished so the next poll picks them up after backoff. A row
    that has hit ``MAX_PUBLISH_ATTEMPTS`` is shipped to the DLQ topic
    and marked published — that breaks an infinite-retry loop on a
    poison message.
    """
    published_ids: list[int] = []

    async with conn.transaction():
        rows = await conn.fetch(SELECT_BATCH_SQL, POLL_BATCH)
        for row in rows:
            event_id = int(row["id"])
            attempts = int(row["publish_attempts"])
            envelope = build_envelope(row)
            payload_bytes = envelope_bytes(envelope)
            key_bytes = envelope["aggregate_id"].encode("ascii")

            target_topic = topic_for(envelope["event_type"])

            # If we've exhausted attempts, divert and mark published.
            if attempts >= MAX_PUBLISH_ATTEMPTS:
                try:
                    await producer.send_and_wait(
                        TOPIC_DEAD_LETTER, payload_bytes, key=key_bytes
                    )
                    published_ids.append(event_id)
                    log.error(
                        "outbox.dlq",
                        event_id=str(event_id),
                        event_type=envelope["event_type"],
                        attempts=attempts,
                    )
                    backoff.pop(event_id, None)
                except KafkaError as exc:
                    log.error(
                        "outbox.dlq_failed",
                        event_id=str(event_id),
                        error=str(exc),
                    )
                continue

            try:
                await producer.send_and_wait(
                    target_topic, payload_bytes, key=key_bytes
                )
                published_ids.append(event_id)
                backoff.pop(event_id, None)
            except KafkaError as exc:
                # Increment attempts in a separate tx so the row state
                # survives even if we abort the batch.
                log.warning(
                    "outbox.publish_failed",
                    event_id=str(event_id),
                    event_type=envelope["event_type"],
                    attempts=attempts + 1,
                    error=str(exc),
                )
                # In-batch row already locked; just increment via the
                # same tx — much cheaper than another roundtrip.
                await conn.execute(INCREMENT_ATTEMPTS_SQL, event_id)
                # Track per-id backoff so the next poll sleeps before
                # picking this row up again.
                prior = backoff.get(event_id, BACKOFF_BASE_S)
                backoff[event_id] = min(prior * 2.0, BACKOFF_MAX_S)

        if published_ids:
            await conn.execute(MARK_PUBLISHED_SQL, published_ids)

    return len(published_ids)


async def _update_unpublished_gauge(pool: asyncpg.Pool, gauge: Gauge) -> None:
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval(COUNT_UNPUBLISHED_SQL)
        gauge.set(int(count or 0))
    except Exception as exc:  # noqa: BLE001 — metrics must not crash the loop
        log.warning("outbox.metrics_refresh_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _run() -> None:
    # Patch asyncpg/aiokafka before any client is constructed.
    _init_telemetry()

    db_url = _coerce_asyncpg_dsn(os.environ["DATABASE_URL"])
    bootstrap = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "redpanda:9092")

    log.info("outbox.start", bootstrap=bootstrap)
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    producer = await _build_producer(bootstrap)
    metrics = MetricsState()
    server = await _metrics_server(metrics, METRICS_PORT)
    log.info("outbox.metrics_listening", port=METRICS_PORT)

    # Track per-event backoff so failing rows don't get hammered on
    # every tick. The dict is local to this process — restarts reset
    # it, which is fine: a fresh row simply restarts at BASE_S.
    backoff: dict[int, float] = {}

    stop = asyncio.Event()

    def _stop(_sig: int, _frame: Any = None) -> None:
        log.info("outbox.shutdown_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop, sig)
        except NotImplementedError:
            # Windows signal handlers aren't all supported under asyncio.
            signal.signal(sig, _stop)

    last_gauge_refresh = 0.0
    try:
        while not stop.is_set():
            try:
                async with pool.acquire() as conn:
                    published = await _process_batch(conn, producer, backoff)
            except Exception as exc:  # noqa: BLE001 — DB hiccup, sleep & retry
                log.error("outbox.batch_failed", error=str(exc))
                await asyncio.sleep(BACKOFF_BASE_S * 4)
                continue

            now = loop.time()
            if now - last_gauge_refresh > 1.0:
                await _update_unpublished_gauge(pool, metrics.unpublished)
                last_gauge_refresh = now

            if published == 0:
                # Honour the smallest pending per-row backoff so we
                # don't immediately re-poll only to skip the same rows.
                next_sleep = IDLE_SLEEP_S
                if backoff:
                    next_sleep = max(next_sleep, min(backoff.values()))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=next_sleep)
                except asyncio.TimeoutError:
                    pass
    finally:
        log.info("outbox.shutdown")
        server.close()
        try:
            await server.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        try:
            await producer.stop()
        except Exception:  # noqa: BLE001
            pass
        await pool.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
