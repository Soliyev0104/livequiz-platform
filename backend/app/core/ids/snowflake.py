"""Snowflake-style 64-bit ID generator.

Bit layout (big-endian, sign bit always zero so values fit in a signed BIGINT):

    0 | 41 bits ms-since-epoch | 10 bits worker_id | 12 bits sequence

The custom epoch (``EPOCH_MS``) shifts the 41-bit timestamp window into the
project lifetime (2026-01-01 + ~69.7 years), keeping IDs short and
JSON-safe. See ``README.md`` for the full rationale and the integration list.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

EPOCH_MS: int = 1767225600000  # 2026-01-01T00:00:00Z

WORKER_ID_BITS: int = 10
SEQUENCE_BITS: int = 12

WORKER_ID_SHIFT: int = SEQUENCE_BITS
TIMESTAMP_SHIFT: int = SEQUENCE_BITS + WORKER_ID_BITS  # 22

MAX_WORKER_ID: int = (1 << WORKER_ID_BITS) - 1  # 1023
SEQUENCE_MASK: int = (1 << SEQUENCE_BITS) - 1  # 4095


class ClockMovedBackwardsError(RuntimeError):
    """Raised when ``clock_fn`` returns a time earlier than the last observed ms.

    Failing closed prevents duplicate IDs being minted across the rollback
    window. Operator response: investigate NTP, then restart the affected
    replica only after the clock has caught up.
    """

    def __init__(self, delta_ms: int) -> None:
        super().__init__(f"Clock moved backwards by {delta_ms} ms")
        self.delta_ms = delta_ms


def _default_clock_ms() -> int:
    return time.time_ns() // 1_000_000


class SnowflakeGenerator:
    """Thread-safe 64-bit Snowflake ID generator.

    The lock is a plain ``threading.Lock`` because ``next_id`` is sync and
    must never be held across ``await``. Async services call ``next_id`` from
    sync code paths (service-layer helpers) only.
    """

    def __init__(
        self,
        worker_id: int,
        *,
        epoch_ms: int = EPOCH_MS,
        clock_fn: Callable[[], int] = _default_clock_ms,
    ) -> None:
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError(
                f"worker_id must be in [0, {MAX_WORKER_ID}], got {worker_id}"
            )
        self.worker_id = worker_id
        self.epoch_ms = epoch_ms
        self._clock_fn = clock_fn
        self._lock = threading.Lock()
        self.last_ms: int = -1
        self.sequence: int = 0

    def next_id(self) -> int:
        with self._lock:
            now = self._clock_fn()
            if now < self.last_ms:
                raise ClockMovedBackwardsError(self.last_ms - now)
            if now == self.last_ms:
                self.sequence = (self.sequence + 1) & SEQUENCE_MASK
                if self.sequence == 0:
                    now = self._wait_until_next_ms(self.last_ms)
            else:
                self.sequence = 0
            self.last_ms = now
            return (
                ((now - self.epoch_ms) << TIMESTAMP_SHIFT)
                | (self.worker_id << WORKER_ID_SHIFT)
                | self.sequence
            )

    def _wait_until_next_ms(self, last_ms: int) -> int:
        now = self._clock_fn()
        while now <= last_ms:
            now = self._clock_fn()
        return now

    def decode(self, snowflake_id: int) -> tuple[int, int, int]:
        """Return ``(timestamp_ms, worker_id, sequence)`` for an emitted ID.

        ``timestamp_ms`` is the absolute wall-clock ms (epoch already added
        back). Used by tests and for ID-to-time debugging.
        """
        sequence = snowflake_id & SEQUENCE_MASK
        worker_id = (snowflake_id >> WORKER_ID_SHIFT) & MAX_WORKER_ID
        timestamp_ms = (snowflake_id >> TIMESTAMP_SHIFT) + self.epoch_ms
        return timestamp_ms, worker_id, sequence


_GENERATOR: SnowflakeGenerator | None = None


def get_id_generator() -> SnowflakeGenerator:
    """Process-level singleton. First call resolves ``SNOWFLAKE_WORKER_ID``.

    Called from ``app.main:lifespan`` so a missing or out-of-range env var
    fails the boot rather than the first ID-generating request.
    """
    global _GENERATOR
    if _GENERATOR is not None:
        return _GENERATOR

    raw_worker = os.environ.get("SNOWFLAKE_WORKER_ID")
    if raw_worker is None or raw_worker == "":
        raise RuntimeError("SNOWFLAKE_WORKER_ID env var is required")
    try:
        worker_id = int(raw_worker)
    except ValueError as exc:
        raise RuntimeError(
            f"SNOWFLAKE_WORKER_ID must be an integer, got {raw_worker!r}"
        ) from exc
    if not 0 <= worker_id <= MAX_WORKER_ID:
        raise RuntimeError(
            f"SNOWFLAKE_WORKER_ID must be in [0, {MAX_WORKER_ID}], got {worker_id}"
        )

    raw_epoch = os.environ.get("SNOWFLAKE_EPOCH_MS")
    epoch_ms = int(raw_epoch) if raw_epoch else EPOCH_MS

    _GENERATOR = SnowflakeGenerator(worker_id=worker_id, epoch_ms=epoch_ms)
    return _GENERATOR
