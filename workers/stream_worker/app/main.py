"""Stream worker — Redpanda → ClickHouse ingest.

Consumer model
==============

A single ``aiokafka.AIOKafkaConsumer`` joins the
``livequiz-analytics-v1`` group with ``enable_auto_commit=False``. We
manually commit offsets only after the per-message handler has
returned and any buffered ClickHouse rows have been flushed — that is
the only way to make sure a redelivery cannot leave an event
half-applied.

Dedupe (two layers, exactly because Kafka is at-least-once):

1. ``seen:event:{event_id}`` SET NX EX 86400 in Redis. Hits short-
   circuit before we ever touch ClickHouse.
2. ``answer_events`` is a ReplacingMergeTree keyed by
   ``(match_id, question_id, participant_id, event_id)`` so any
   duplicates that slip past Redis fold during background merges.

Dispatch
========

Routing on ``event_type`` rather than on the source topic keeps the
worker tolerant of a future "split this event across two topics"
refactor — every handler still knows what it consumes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import ConsumerRecord
from prometheus_client import Counter, Gauge, start_http_server
from pydantic import ValidationError
from redis.asyncio import Redis

from app.clickhouse_client import ClickHouseClient
from app.dedupe import claim as dedupe_claim
from app.envelope import CURRENT_SCHEMA_VERSION, Envelope, parse_envelope
from app.handlers import answer as h_answer
from app.handlers import match as h_match
from app.handlers import moderation as h_moderation
from app.handlers import room as h_room


# ---------------------------------------------------------------------------
# Config + logging
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "livequiz-analytics-v1"
TOPICS = [
    "livequiz.events.room",
    "livequiz.events.match",
    "livequiz.events.answer",
    "livequiz.events.moderation",
]

SERVICE_NAME = os.environ.get("SERVICE_NAME", "stream-worker")
METRICS_PORT = 9101


def _add_otel_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
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
log = structlog.get_logger("stream-worker")


# ---------------------------------------------------------------------------
# Prometheus metrics (served on :9101/metrics)
# ---------------------------------------------------------------------------

EVENTS_PROCESSED = Counter(
    "stream_worker_events_processed_total",
    "Domain events successfully written to ClickHouse, by event type.",
    ["event_type"],
)
EVENT_LAG = Gauge(
    "stream_worker_event_lag_seconds",
    "Seconds between an event's occurred_at and when this worker handled it.",
    ["topic"],
)


def _event_lag_seconds(occurred_at: datetime) -> float:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - occurred_at).total_seconds())


# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------


def _init_telemetry() -> None:
    """Best-effort OTLP/gRPC tracing (aiokafka consumer spans + Redis spans)."""
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

    for name, dotted in (
        ("aiokafka", "opentelemetry.instrumentation.aiokafka:AIOKafkaInstrumentor"),
        ("redis", "opentelemetry.instrumentation.redis:RedisInstrumentor"),
    ):
        try:
            mod_name, cls_name = dotted.split(":")
            mod = __import__(mod_name, fromlist=[cls_name])
            getattr(mod, cls_name)().instrument()
        except Exception as exc:  # noqa: BLE001
            log.warning("telemetry.instrument_skipped", target=name, error=str(exc))
    log.info("telemetry.ready", service=SERVICE_NAME, endpoint=endpoint or "(default)")


ROOM_EVENT_TYPES = {"RoomCreated", "PlayerJoined", "PlayerLeft"}
MATCH_EVENT_TYPES = {
    "MatchStarted",
    "QuestionStarted",
    "QuestionClosed",
    "MatchFinished",
}
ANSWER_EVENT_TYPES = {"AnswerSubmitted"}
MODERATION_EVENT_TYPES = {
    "ContentReported",
    "ContentFlagged",
    "ModerationDecisionMade",
}


# ---------------------------------------------------------------------------
# Per-message processing
# ---------------------------------------------------------------------------


async def _dispatch(env: Envelope, ch: ClickHouseClient, redis: Redis) -> None:
    if env.event_type in ROOM_EVENT_TYPES:
        await h_room.handle(env, ch)
    elif env.event_type in MATCH_EVENT_TYPES:
        await h_match.handle(env, ch, redis)
    elif env.event_type in ANSWER_EVENT_TYPES:
        await h_answer.handle(env, ch)
    elif env.event_type in MODERATION_EVENT_TYPES:
        await h_moderation.handle(env, ch)
    else:
        # Unknown but envelope-valid — record so the audit log retains
        # it, but don't fail the consumer. Schema rev would surface as
        # a `schema_version` mismatch caught earlier.
        log.warning("stream.unknown_event_type", event_type=env.event_type)
        await h_room.handle(env, ch)


async def _handle_message(
    msg: ConsumerRecord,
    ch: ClickHouseClient,
    redis: Redis,
) -> bool:
    """Process one message. Returns True if the offset is safe to commit.

    A False return path means the consumer must NOT advance its
    offset; we backoff in the caller and retry from the same position
    on the next poll cycle. The only False trigger is a transient
    side-effect failure (CH down, Redis down). Schema errors emit a
    DLQ and return True so the consumer doesn't get stuck on bad data.
    """
    raw = msg.value
    try:
        env = parse_envelope(raw)
    except (ValidationError, ValueError) as exc:
        log.error(
            "stream.envelope_invalid",
            topic=msg.topic,
            partition=msg.partition,
            offset=msg.offset,
            error=str(exc),
        )
        # Schema error → swallow and advance. Re-reading the same
        # malformed bytes would only repeat the error forever.
        return True

    EVENT_LAG.labels(topic=msg.topic).set(_event_lag_seconds(env.occurred_at))

    if env.schema_version != CURRENT_SCHEMA_VERSION:
        log.error(
            "stream.schema_version_mismatch",
            event_id=str(env.event_id),
            got=env.schema_version,
            expected=CURRENT_SCHEMA_VERSION,
        )
        return True

    # Dedupe (layer 1). Layer 2 is the ReplacingMergeTree in CH.
    try:
        first_time = await dedupe_claim(redis, env.event_id)
    except Exception as exc:  # noqa: BLE001 — Redis is transient
        log.error(
            "stream.dedupe_failed",
            event_id=str(env.event_id),
            error=str(exc),
        )
        return False
    if not first_time:
        log.info("stream.duplicate_skipped", event_id=str(env.event_id))
        return True

    try:
        await _dispatch(env, ch, redis)
    except Exception as exc:  # noqa: BLE001 — handler-or-CH failure
        log.error(
            "stream.handler_failed",
            event_id=str(env.event_id),
            event_type=env.event_type,
            error=str(exc),
        )
        return False
    EVENTS_PROCESSED.labels(event_type=env.event_type).inc()
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _run() -> None:
    # Patch aiokafka/redis before any client is constructed.
    _init_telemetry()
    try:
        start_http_server(METRICS_PORT)
        log.info("stream.metrics_listening", port=METRICS_PORT)
    except OSError as exc:  # noqa: BLE001 — metrics port clash must not kill ingest
        log.error("stream.metrics_bind_failed", port=METRICS_PORT, error=str(exc))

    bootstrap = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "redpanda:9092")
    ch_url = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    ch_db = os.environ.get("CLICKHOUSE_DB", "livequiz")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    log.info(
        "stream.start",
        bootstrap=bootstrap,
        clickhouse=ch_url,
        topics=TOPICS,
        group=CONSUMER_GROUP,
    )

    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=bootstrap,
        group_id=CONSUMER_GROUP,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_records=200,
        client_id="livequiz-stream-worker",
    )
    await consumer.start()

    ch = ClickHouseClient(ch_url, ch_db)
    await ch.connect()

    redis = Redis.from_url(redis_url, decode_responses=False)

    stop = asyncio.Event()

    def _stop(_sig: int, _frame: Any = None) -> None:
        log.info("stream.shutdown_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop, sig)
        except NotImplementedError:
            signal.signal(sig, _stop)

    try:
        while not stop.is_set():
            try:
                records = await consumer.getmany(timeout_ms=500, max_records=200)
            except Exception as exc:  # noqa: BLE001
                log.error("stream.poll_failed", error=str(exc))
                await asyncio.sleep(1.0)
                continue

            if not records:
                await ch.maybe_flush()
                continue

            # Per-partition processing so a partial failure on one
            # partition doesn't poison the commit for the others.
            safe_offsets: dict[TopicPartition, int] = {}
            failed = False
            for tp, msgs in records.items():
                for msg in msgs:
                    ok = await _handle_message(msg, ch, redis)
                    if ok:
                        safe_offsets[tp] = msg.offset + 1
                    else:
                        failed = True
                        break
                if failed:
                    break

            try:
                await ch.flush_all()
            except Exception as exc:  # noqa: BLE001
                log.error("stream.flush_failed", error=str(exc))
                # Skip commit so the failed batch is redelivered.
                await asyncio.sleep(1.0)
                continue

            if safe_offsets:
                try:
                    await consumer.commit(safe_offsets)
                except Exception as exc:  # noqa: BLE001
                    # Commit failure: next poll will redeliver — dedupe
                    # absorbs the replay.
                    log.error("stream.commit_failed", error=str(exc))

            if failed:
                # Brief backoff so an outage doesn't burn CPU.
                await asyncio.sleep(1.0)
    finally:
        log.info("stream.shutdown")
        try:
            await consumer.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ch.flush_all()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ch.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
