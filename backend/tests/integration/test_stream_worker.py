"""Integration test for the stream worker.

Stand up Kafka + ClickHouse + Redis; produce the same
``AnswerSubmitted`` envelope twice; run the worker for a short window;
assert that:

1. ``livequiz.events_raw`` has exactly one row for that event_id.
2. ``livequiz.answer_events`` has exactly one row.

The duplicate path tests the Redis dedupe (layer 1) — a second
delivery of the same ``event_id`` is short-circuited before the
ClickHouse handlers run.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaProducer
from testcontainers.clickhouse import ClickHouseContainer
from testcontainers.kafka import KafkaContainer
from testcontainers.redis import RedisContainer


pytestmark = pytest.mark.asyncio(loop_scope="session")


_WORKER_PATH = (
    Path(__file__).resolve().parents[3] / "workers" / "stream_worker"
)


@pytest.fixture(scope="session")
def worker_path_on_syspath() -> Iterator[None]:
    sys.path.insert(0, str(_WORKER_PATH))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(_WORKER_PATH))
        except ValueError:
            pass


@pytest.fixture(scope="session")
def kafka_for_stream() -> Iterator[KafkaContainer]:
    with KafkaContainer() as k:
        yield k


@pytest.fixture(scope="session")
def clickhouse_for_stream() -> Iterator[ClickHouseContainer]:
    with ClickHouseContainer("clickhouse/clickhouse-server:24.8") as ch:
        yield ch


@pytest.fixture(scope="session")
def redis_for_stream() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest_asyncio.fixture(loop_scope="session")
async def ch_initialised(
    clickhouse_for_stream: ClickHouseContainer,
) -> AsyncIterator[str]:
    """Run the project's ClickHouse migrations against the container."""
    from clickhouse_connect import get_client

    repo_root = Path(__file__).resolve().parents[3]
    sql_files = [
        repo_root / "migrations" / "clickhouse" / "001_events.sql",
        repo_root / "migrations" / "clickhouse" / "002_analytics_views.sql",
    ]

    host = clickhouse_for_stream.get_container_host_ip()
    port = clickhouse_for_stream.get_exposed_port(8123)
    url = f"http://{host}:{port}"

    def _run_migrations() -> None:
        client = get_client(host=host, port=int(port), database="default")
        try:
            for path in sql_files:
                sql = path.read_text()
                # Split on `;\n` so each DDL runs as its own command —
                # clickhouse-connect's exec API takes one statement.
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    client.command(stmt)
        finally:
            client.close()

    await asyncio.to_thread(_run_migrations)
    yield url


async def _produce_envelope(bootstrap: str, topic: str, envelope: dict) -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        acks="all",
        enable_idempotence=True,
    )
    await producer.start()
    try:
        await producer.send_and_wait(
            topic, json.dumps(envelope).encode("utf-8")
        )
    finally:
        await producer.stop()


async def _ch_count(host: str, port: int, table: str, where: str) -> int:
    from clickhouse_connect import get_client

    def _go() -> int:
        client = get_client(host=host, port=port, database="default")
        try:
            rows = client.query(f"SELECT count() FROM {table} WHERE {where}").result_rows
            return int(rows[0][0]) if rows else 0
        finally:
            client.close()

    return await asyncio.to_thread(_go)


async def test_duplicate_envelope_is_deduped(
    worker_path_on_syspath: None,
    kafka_for_stream: KafkaContainer,
    ch_initialised: str,
    clickhouse_for_stream: ClickHouseContainer,
    redis_for_stream: RedisContainer,
) -> None:
    bootstrap = kafka_for_stream.get_bootstrap_server()

    redis_url = (
        f"redis://{redis_for_stream.get_container_host_ip()}:"
        f"{redis_for_stream.get_exposed_port(6379)}/0"
    )
    ch_host = clickhouse_for_stream.get_container_host_ip()
    ch_port = int(clickhouse_for_stream.get_exposed_port(8123))
    ch_url = f"http://{ch_host}:{ch_port}"

    import os

    os.environ["REDPANDA_BOOTSTRAP_SERVERS"] = bootstrap
    os.environ["CLICKHOUSE_URL"] = ch_url
    os.environ["CLICKHOUSE_DB"] = "livequiz"
    os.environ["REDIS_URL"] = redis_url

    # Save and clear the backend `app` packages so the worker's `app`
    # wins for the duration of this test. Restored in `finally`.
    saved_modules = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "app" or name.startswith("app.")
    }
    try:
        worker_main = importlib.import_module("app.main")

        event_id = 555000111
        envelope = {
            "event_id": str(event_id),
            "event_type": "AnswerSubmitted",
            "aggregate_type": "answer",
            "aggregate_id": str(event_id),
            "occurred_at": datetime.now(tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "producer": "livequiz-api",
            "schema_version": 1,
            "payload": {
                "match_id": "9001",
                "room_id": "8001",
                "participant_id": "7001",
                "question_id": "5001",
                "is_correct": True,
                "score_awarded": 700,
                "response_time_ms": 1234,
            },
        }

        # Produce TWICE — same event_id, same payload.
        await _produce_envelope(bootstrap, "livequiz.events.answer", envelope)
        await _produce_envelope(bootstrap, "livequiz.events.answer", envelope)

        # Run the consumer for ~6s or until both tables show one row.
        task = asyncio.create_task(worker_main._run(), name="stream-worker-under-test")
        try:
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                raw_count = await _ch_count(
                    ch_host,
                    ch_port,
                    "livequiz.events_raw",
                    f"event_id = {event_id}",
                )
                ans_count = await _ch_count(
                    ch_host,
                    ch_port,
                    "livequiz.answer_events",
                    f"event_id = {event_id}",
                )
                if raw_count >= 1 and ans_count >= 1:
                    # Give the worker a brief settle window so a 2nd
                    # in-flight delivery has a chance to land too.
                    await asyncio.sleep(1.5)
                    break
                await asyncio.sleep(0.3)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, SystemExit):
                pass
            except Exception:
                pass

        raw_count = await _ch_count(
            ch_host, ch_port, "livequiz.events_raw", f"event_id = {event_id}"
        )
        ans_count = await _ch_count(
            ch_host,
            ch_port,
            "livequiz.answer_events",
            f"event_id = {event_id}",
        )

        assert raw_count == 1, f"events_raw must have exactly 1 row, got {raw_count}"
        assert ans_count == 1, f"answer_events must have exactly 1 row, got {ans_count}"
    finally:
        for name in [
            n for n in list(sys.modules) if n == "app" or n.startswith("app.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
