"""Thin async wrapper over ``clickhouse-connect``.

The underlying driver is synchronous; we call it from
``asyncio.to_thread`` so the consumer loop stays cooperative. Rows are
buffered per-table and flushed when the row count reaches the batch
size or when ``flush_interval_ms`` elapses — whichever comes first.

Two flush triggers, one common code path:

* Size trigger — handler call sees the buffer just crossed the
  threshold and forces a flush before returning. This is the steady
  path under load.
* Time trigger — the consumer loop calls :meth:`maybe_flush` between
  poll cycles so a low-throughput match still drains the buffer.

Offsets must NEVER be committed before a flush has succeeded; the
consumer in ``main.py`` calls :meth:`flush_all` before committing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence

from clickhouse_connect import get_client


log = logging.getLogger("stream-worker.clickhouse")


class ClickHouseClient:
    def __init__(
        self,
        url: str,
        database: str,
        *,
        batch_rows: int = 100,
        flush_interval_ms: int = 500,
    ) -> None:
        self._url = url
        self._database = database
        self._batch_rows = batch_rows
        self._flush_interval = flush_interval_ms / 1000.0
        self._client: Any = None
        self._buffers: dict[str, tuple[list[Sequence[Any]], list[str]]] = {}
        self._last_flush: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        def _connect() -> Any:
            return get_client(
                dsn=self._url,
                database=self._database,
                send_receive_timeout=5,
                connect_timeout=3,
            )

        self._client = await asyncio.to_thread(_connect)

    async def close(self) -> None:
        if self._client is None:
            return
        client = self._client
        self._client = None
        await asyncio.to_thread(client.close)

    async def _do_insert(
        self, table: str, rows: list[Sequence[Any]], columns: list[str]
    ) -> None:
        if not rows:
            return
        if self._client is None:
            raise RuntimeError("ClickHouseClient.connect() not called")
        client = self._client

        def _insert() -> None:
            client.insert(table, rows, column_names=columns)

        await asyncio.to_thread(_insert)

    async def insert_many(
        self,
        table: str,
        rows: Sequence[Sequence[Any]],
        columns: Sequence[str],
    ) -> None:
        """Append rows to the in-memory buffer for ``table``.

        Flushes synchronously when the batch fills. ``columns`` is
        recorded the first time we see a table — subsequent calls must
        pass an identical list (mismatches would mean a code bug, not
        recoverable state).
        """
        async with self._lock:
            existing = self._buffers.get(table)
            if existing is None:
                buf: list[Sequence[Any]] = []
                col_list = list(columns)
                self._buffers[table] = (buf, col_list)
                self._last_flush[table] = time.monotonic()
            else:
                buf, col_list = existing
            buf.extend(list(r) for r in rows)
            full = len(buf) >= self._batch_rows
            if full:
                drained = buf[:]
                buf.clear()
                cols = list(col_list)
                self._last_flush[table] = time.monotonic()
            else:
                drained = []
                cols = []

        if drained:
            await self._do_insert(table, drained, cols)

    async def maybe_flush(self) -> None:
        """Flush buffers whose ``flush_interval`` has elapsed.

        Called by the consumer loop between poll cycles so trickle
        traffic still lands in ClickHouse within the configured time
        budget instead of waiting forever for a full batch.
        """
        now = time.monotonic()
        to_flush: list[tuple[str, list[Sequence[Any]], list[str]]] = []
        async with self._lock:
            for table, (buf, cols) in self._buffers.items():
                if not buf:
                    continue
                if now - self._last_flush.get(table, 0.0) >= self._flush_interval:
                    to_flush.append((table, buf[:], list(cols)))
                    buf.clear()
                    self._last_flush[table] = now
        for table, rows, cols in to_flush:
            await self._do_insert(table, rows, cols)

    async def flush_all(self) -> None:
        """Drain every buffer. Called before committing Kafka offsets."""
        to_flush: list[tuple[str, list[Sequence[Any]], list[str]]] = []
        async with self._lock:
            for table, (buf, cols) in self._buffers.items():
                if not buf:
                    continue
                to_flush.append((table, buf[:], list(cols)))
                buf.clear()
                self._last_flush[table] = time.monotonic()
        for table, rows, cols in to_flush:
            await self._do_insert(table, rows, cols)

    async def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        """One-shot read. Used by analytics queries from the API, not
        the consumer loop — wrap-and-go pattern keeps offhand reads
        from leaking sync calls into the event loop."""
        if self._client is None:
            raise RuntimeError("ClickHouseClient.connect() not called")
        client = self._client

        def _query() -> Any:
            return client.query(query, parameters=parameters or {})

        return await asyncio.to_thread(_query)
