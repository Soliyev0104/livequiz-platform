# Snowflake-Style ID Generator

The from-scratch system component for report §9 (`docs/15_report_outline.md`).
Source-of-truth design doc: `docs/10_from_scratch_component_snowflake.md`.

## Bit layout

A 64-bit positive integer:

```
 63   62                                      22 21              12 11           0
  |   |                                        |  |               |  |           |
  +---+----------------------------------------+--+---------------+--+-----------+
  | 0 |        41 bits  ms since EPOCH_MS      |  10 bits worker  |  12 bits seq |
  +---+----------------------------------------+--+---------------+--+-----------+
```

- **Bit 63 (sign)** is always `0`. Values fit in a signed 64-bit `BIGINT` so
  Postgres and the JVM tooling we don't use today still see positive numbers.
- **Bits 62–22 (timestamp, 41 bits)**: milliseconds since `EPOCH_MS`. Custom
  epoch lets the timestamp window cover the project's lifetime without
  burning bits on the years before 2026.
- **Bits 21–12 (worker_id, 10 bits)**: 0–1023. Operator-assigned per replica
  via `SNOWFLAKE_WORKER_ID`. Uniqueness across replicas is the only mechanism
  preventing cross-machine collisions, so the deployment must enforce it.
- **Bits 11–0 (sequence, 12 bits)**: 0–4095, per-worker per-millisecond. On
  overflow the generator busy-waits until the next millisecond.

## Custom epoch

```
EPOCH_MS = 1767225600000   # 2026-01-01T00:00:00Z
```

Anchoring the epoch at the project start keeps the high bits empty for
years and produces compact IDs that survive JavaScript's `Number.MAX_SAFE_INTEGER`
(2^53 − 1) until the timestamp portion saturates that ceiling — well past the
course's grading window. Beyond that, clients should treat IDs as opaque
strings (the API already serializes them as strings on the wire).

## Capacity

| Dimension                   | Limit                                         |
|-----------------------------|-----------------------------------------------|
| IDs per ms per worker       | 4096                                          |
| Worker replicas             | 1024                                          |
| Platform-wide IDs per ms    | 4096 × 1024 = 4,194,304                       |
| Timestamp horizon           | 2^41 ms ≈ 69.7 years from epoch (≈ 2095)      |

## Why chosen

- **Sortable.** Sequential IDs reflect creation time, so primary-key indexes
  stay tight under append-mostly workloads (matches, submissions, outbox).
- **No central allocator.** Each replica mints IDs in-process, so insert
  latency does not depend on a Postgres sequence round-trip.
- **Debuggable.** The timestamp is recoverable with `decode()`, which is
  invaluable when correlating outbox rows with WebSocket traces.
- **Demonstrates a from-scratch DDIA component.** UUIDv4 would have been
  trivially `uuid.uuid4()`; this implementation actually builds the artefact.

## Integration points

Every ID-bearing record in the system uses this generator at the service
layer (no autoincrement on Postgres PKs):

- `users.id`
- `quiz_sets.id`
- `questions.id`
- `rooms.id`
- `matches.id`
- `answer_submissions.id`
- `outbox_events.id`
- domain `event_id` carried through the outbox → Redpanda → ClickHouse pipeline
- WebSocket server-emitted `message_id`

## Worker ID assignment

Wired identically in `env/.env.example` and `docker-compose.yml`. Operator
must keep these unique across replicas — the generator cannot detect a
duplicate worker_id remotely.

| Service             | `SNOWFLAKE_WORKER_ID` |
|---------------------|-----------------------|
| `api-a`             | 1                     |
| `api-b`             | 2                     |
| `outbox-publisher`  | 10                    |
| `stream-worker`     | 20                    |
| `scheduler`         | 30                    |
| tests (reserved)    | 9                     |

## Trade-offs and limitations

**Pros**

- Low-latency ID minting (no I/O).
- Time-sortable PKs improve B-tree locality and pagination.
- Decoupled from the database — works in workers that never touch Postgres.

**Cons**

- Depends on a monotonic system clock. NTP step-backs raise
  `ClockMovedBackwardsError` rather than producing duplicates (fail-closed).
- Worker uniqueness is operator-enforced; a misconfigured env can collide IDs
  silently.
- Reveals approximate creation time. Acceptable for internal IDs; opaque
  public tokens (refresh tokens, session keys) use cryptographic randoms
  instead.
- Not cryptographically random — never use a Snowflake ID as a security token.

## Failure mode

`ClockMovedBackwardsError` carries `delta_ms`. The generator does **not**
sleep through the rollback because the lock is held; instead it fails the
caller and lets the deployment respond:

1. Investigate clock source (NTP, host time drift).
2. Stop the affected replica.
3. Restart only after the system clock has caught up to the last observed
   `last_ms` — easy to verify because `delta_ms` tells you how long.

## Testing strategy

Determinism via constructor-injected `clock_fn: Callable[[], int]`:

- Default clock is `time.time_ns() // 1_000_000`; production code never
  needs to override it.
- Tests pass a closure over a list iterator or counter so the suite runs
  without `time.sleep` and without flakes on slow CI.
- The reserved test `worker_id` is **9**.

`backend/tests/unit/test_snowflake.py` covers the seven cases required by
phase 01:

1. Sign bit is zero / value is positive.
2. Strictly monotonic across 1000 calls on a single generator.
3. 5000 IDs within one test are unique.
4. Two generators with different `worker_id` never collide even on the same
   millisecond.
5. Clock rollback raises `ClockMovedBackwardsError` with the correct delta.
6. Sequence overflow waits for the next millisecond (fake clock returns the
   same ms 5000 times, then advances).
7. `decode(next_id())` round-trips `(timestamp_ms, worker_id, sequence)`.

## Alternatives rejected

- **UUIDv4** — simple and conflict-free, but not sortable, has no embedded
  timestamp, and demonstrates none of the system-design content the rubric
  rewards.
- **Postgres sequences / `bigserial`** — safe but centralises ID allocation
  on the OLTP database, which is a poor fit for outbox writes that already
  fan out to Redpanda and ClickHouse.
- **ULID** — close runner-up (sortable, 128-bit). Rejected because the
  64-bit footprint matters for the outbox row size and event-stream
  bandwidth, and the worker-id field is exactly the artefact we want to
  showcase as a distributed-systems component.

## Public API surface

```python
from app.core.ids import (
    SnowflakeGenerator,
    ClockMovedBackwardsError,
    get_id_generator,
)

gen = get_id_generator()        # process-level singleton, env-driven
new_id = gen.next_id()          # int, 19 digits, positive
ts_ms, worker, seq = gen.decode(new_id)
```

`get_id_generator()` is invoked once during `app.main:lifespan` so a missing
`SNOWFLAKE_WORKER_ID` aborts the boot before traffic hits the replica.
