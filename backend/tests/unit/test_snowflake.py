"""Unit tests for the Snowflake ID generator. Deterministic via injected clocks."""

from __future__ import annotations

from typing import Callable

import pytest

from app.core.ids import ClockMovedBackwardsError, SnowflakeGenerator
from app.core.ids.snowflake import EPOCH_MS, SEQUENCE_MASK

TEST_WORKER_ID = 9  # reserved test worker per env/.env.example
T0 = EPOCH_MS + 1_000  # 1 second after the custom epoch


def fixed_clock(value: int) -> Callable[[], int]:
    def _clock() -> int:
        return value

    return _clock


def advancing_clock(start: int) -> Callable[[], int]:
    state = [start - 1]

    def _clock() -> int:
        state[0] += 1
        return state[0]

    return _clock


def scripted_clock(values: list[int]) -> Callable[[], int]:
    it = iter(values)

    def _clock() -> int:
        return next(it)

    return _clock


def fixed_then_advance_clock(
    fixed_value: int, fixed_count: int, advanced_value: int
) -> Callable[[], int]:
    """Return ``fixed_value`` for the first ``fixed_count`` calls, then ``advanced_value``."""
    state = [0]

    def _clock() -> int:
        state[0] += 1
        if state[0] <= fixed_count:
            return fixed_value
        return advanced_value

    return _clock


def test_generates_positive_int() -> None:
    gen = SnowflakeGenerator(worker_id=TEST_WORKER_ID, clock_fn=fixed_clock(T0))
    snowflake_id = gen.next_id()
    assert snowflake_id > 0
    assert snowflake_id >> 63 == 0  # sign bit is always 0


def test_monotonic_for_one_generator() -> None:
    gen = SnowflakeGenerator(worker_id=TEST_WORKER_ID, clock_fn=advancing_clock(T0))
    ids = [gen.next_id() for _ in range(1000)]
    assert all(later > earlier for earlier, later in zip(ids, ids[1:]))


def test_5000_ids_unique() -> None:
    gen = SnowflakeGenerator(worker_id=TEST_WORKER_ID, clock_fn=advancing_clock(T0))
    ids = [gen.next_id() for _ in range(5000)]
    assert len(set(ids)) == 5000


def test_different_worker_ids_never_collide() -> None:
    gen_a = SnowflakeGenerator(worker_id=TEST_WORKER_ID, clock_fn=fixed_clock(T0))
    gen_b = SnowflakeGenerator(worker_id=TEST_WORKER_ID + 1, clock_fn=fixed_clock(T0))

    # Generate within the per-ms sequence budget so neither hits busy-wait.
    count_per_worker = 1000
    ids_a = [gen_a.next_id() for _ in range(count_per_worker)]
    ids_b = [gen_b.next_id() for _ in range(count_per_worker)]

    assert set(ids_a).isdisjoint(set(ids_b))
    assert all(gen_a.decode(i)[1] == TEST_WORKER_ID for i in ids_a)
    assert all(gen_b.decode(i)[1] == TEST_WORKER_ID + 1 for i in ids_b)


def test_clock_rollback_raises() -> None:
    gen = SnowflakeGenerator(
        worker_id=TEST_WORKER_ID, clock_fn=scripted_clock([T0, T0 - 5])
    )
    gen.next_id()  # primes last_ms = T0
    with pytest.raises(ClockMovedBackwardsError) as exc_info:
        gen.next_id()
    assert exc_info.value.delta_ms == 5


def test_sequence_overflow_waits_for_next_ms() -> None:
    # Clock returns T0 for 5000 calls, then T0+1. Plenty of headroom for the
    # 4096 sequence-fill calls plus the busy-wait poll inside next_id #4097.
    gen = SnowflakeGenerator(
        worker_id=TEST_WORKER_ID,
        clock_fn=fixed_then_advance_clock(T0, 5000, T0 + 1),
    )

    ids = [gen.next_id() for _ in range(4097)]

    # First (SEQUENCE_MASK + 1) IDs filled the sequence at T0.
    for seq, snowflake_id in enumerate(ids[: SEQUENCE_MASK + 1]):
        ts, worker, decoded_seq = gen.decode(snowflake_id)
        assert ts == T0
        assert worker == TEST_WORKER_ID
        assert decoded_seq == seq

    # The 4097th ID rolled over to the next millisecond, sequence reset to 0.
    ts, worker, decoded_seq = gen.decode(ids[SEQUENCE_MASK + 1])
    assert ts == T0 + 1
    assert worker == TEST_WORKER_ID
    assert decoded_seq == 0


def test_decode_round_trip() -> None:
    timestamps = [T0, T0 + 7, T0 + 99]
    gen = SnowflakeGenerator(
        worker_id=TEST_WORKER_ID, clock_fn=scripted_clock(list(timestamps))
    )

    for expected_ts in timestamps:
        snowflake_id = gen.next_id()
        ts, worker, seq = gen.decode(snowflake_id)
        assert (ts, worker, seq) == (expected_ts, TEST_WORKER_ID, 0)
