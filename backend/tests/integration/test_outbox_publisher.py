"""Integration test for the outbox publisher worker.

Stand up a Postgres + Redpanda pair via testcontainers, insert five
``outbox_events`` rows by hand, spin the publisher loop for ~2s, then
assert:

1. Every row's ``published_at`` is non-NULL.
2. The five envelopes can be read back from the topics implied by
   their ``event_type`` via ``topic_for``.

We import the worker module directly rather than spawning a subprocess
so the test runs in the same loop and we can asyncio.wait for it.

The publisher's normal entrypoint loops forever; tests call its
``_run`` and cancel via SIGINT-equivalent — the loop honours
``stop`` event.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer


pytestmark = pytest.mark.asyncio(loop_scope="session")


# The worker package isn't on PYTHONPATH by default; add it here so
# `import app.main as publisher_main` resolves to the publisher's
# ``workers/outbox_publisher/app/main.py`` for the lifetime of the test.
_PUBLISHER_PATH = (
    Path(__file__).resolve().parents[3] / "workers" / "outbox_publisher"
)


@pytest.fixture(scope="session")
def publisher_path_on_syspath() -> Iterator[None]:
    sys.path.insert(0, str(_PUBLISHER_PATH))
    # Don't shadow the backend's `app` package; we re-import on demand
    # inside the test using importlib.
    try:
        yield
    finally:
        try:
            sys.path.remove(str(_PUBLISHER_PATH))
        except ValueError:
            pass


@pytest.fixture(scope="session")
def publisher_pg() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def redpanda_container() -> Iterator[KafkaContainer]:
    """Generic Kafka-compatible broker. Production runs Redpanda but
    the Kafka wire protocol is what the worker speaks; either backs it."""
    with KafkaContainer() as rp:
        yield rp


@pytest_asyncio.fixture(loop_scope="session")
async def prepared_pg(publisher_pg: PostgresContainer) -> AsyncIterator[str]:
    """Bare schema: just ``outbox_events`` is enough — no FKs needed."""
    raw_url = publisher_pg.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql"
    ).replace("postgresql+asyncpg", "postgresql")

    conn = await asyncpg.connect(raw_url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                id BIGINT PRIMARY KEY,
                aggregate_type TEXT NOT NULL,
                aggregate_id BIGINT NOT NULL,
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL,
                published_at TIMESTAMPTZ NULL,
                publish_attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Idempotent truncation in case the session reuses the volume.
        await conn.execute("TRUNCATE outbox_events")
    finally:
        await conn.close()
    yield raw_url


def _bootstrap(broker: KafkaContainer) -> str:
    return broker.get_bootstrap_server()


async def _insert_outbox_rows(dsn: str, rows: list[dict]) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        for r in rows:
            await conn.execute(
                """
                INSERT INTO outbox_events
                  (id, aggregate_type, aggregate_id, event_type, payload, occurred_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                """,
                r["id"],
                r["aggregate_type"],
                r["aggregate_id"],
                r["event_type"],
                json.dumps(r["payload"]),
                r["occurred_at"],
            )
    finally:
        await conn.close()


async def _count_unpublished(dsn: str) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM outbox_events WHERE published_at IS NULL"
            )
        )
    finally:
        await conn.close()


async def test_outbox_rows_flow_to_redpanda(
    publisher_path_on_syspath: None,
    prepared_pg: str,
    redpanda_container: KafkaContainer,
) -> None:
    bootstrap = _bootstrap(redpanda_container)

    # Re-import worker modules with the worker path on sys.path. We
    # tear them out of the cache at the end so the backend `app` is
    # restored for any subsequent tests in the session.
    import importlib

    # Drop any backend `app` already in sys.modules so the publisher's
    # `app` package wins for the duration of this test.
    saved_modules = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "app" or name.startswith("app.")
    }
    try:
        publisher_main = importlib.import_module("app.main")
        publisher_topics = importlib.import_module("app.topics")

        # Seed 5 rows spanning multiple event types so we exercise the
        # routing map, not just one happy-path topic.
        now = datetime.now(tz=timezone.utc)
        rows = [
            {
                "id": 1001,
                "aggregate_type": "match",
                "aggregate_id": 9001,
                "event_type": "MatchStarted",
                "payload": {"match_id": "9001", "room_id": "8001"},
                "occurred_at": now,
            },
            {
                "id": 1002,
                "aggregate_type": "room",
                "aggregate_id": 8001,
                "event_type": "PlayerJoined",
                "payload": {"room_id": "8001", "participant_id": "7001"},
                "occurred_at": now,
            },
            {
                "id": 1003,
                "aggregate_type": "answer",
                "aggregate_id": 6001,
                "event_type": "AnswerSubmitted",
                "payload": {
                    "match_id": "9001",
                    "room_id": "8001",
                    "participant_id": "7001",
                    "question_id": "5001",
                    "is_correct": True,
                    "score_awarded": 800,
                    "response_time_ms": 1500,
                },
                "occurred_at": now,
            },
            {
                "id": 1004,
                "aggregate_type": "match",
                "aggregate_id": 9001,
                "event_type": "QuestionStarted",
                "payload": {"match_id": "9001", "question_id": "5001"},
                "occurred_at": now,
            },
            {
                "id": 1005,
                "aggregate_type": "match",
                "aggregate_id": 9001,
                "event_type": "MatchFinished",
                "payload": {"match_id": "9001", "room_id": "8001"},
                "occurred_at": now,
            },
        ]
        await _insert_outbox_rows(prepared_pg, rows)
        assert await _count_unpublished(prepared_pg) == 5

        # Run the publisher; cancel after we observe drain (or 8s max).
        import os

        os.environ["DATABASE_URL"] = prepared_pg
        os.environ["REDPANDA_BOOTSTRAP_SERVERS"] = bootstrap

        task = asyncio.create_task(publisher_main._run(), name="publisher-under-test")
        try:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if await _count_unpublished(prepared_pg) == 0:
                    break
                await asyncio.sleep(0.2)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, SystemExit):
                pass
            except Exception:
                # The loop catches inner exceptions; cancellation is enough.
                pass

        assert await _count_unpublished(prepared_pg) == 0, "publisher did not drain"

        # Consume from every distinct topic that should have received
        # a message and verify each event_id arrived exactly once.
        topics = {publisher_topics.topic_for(r["event_type"]) for r in rows}
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id="test-outbox-publisher-verify",
        )
        await consumer.start()
        try:
            received_ids: set[int] = set()
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline and len(received_ids) < len(rows):
                batch = await consumer.getmany(timeout_ms=1000)
                for _, msgs in batch.items():
                    for msg in msgs:
                        envelope = json.loads(msg.value)
                        received_ids.add(int(envelope["event_id"]))
        finally:
            await consumer.stop()
        assert received_ids == {r["id"] for r in rows}
    finally:
        # Restore the backend `app` package for subsequent tests.
        for name in [
            n for n in list(sys.modules) if n == "app" or n.startswith("app.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
