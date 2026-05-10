# From-Scratch Component — Snowflake-Style ID Generator

## Why this component

A Snowflake-style generator is a core system-design component. It creates sortable, unique 64-bit IDs without calling the database sequence for every object. It fits this project because rooms, matches, submissions, and events are created frequently and IDs should be traceable, compact, and ordered by time.

## Bit layout

Use a 64-bit positive integer:

```text
0 | 41 bits timestamp ms | 10 bits worker id | 12 bits sequence
```

- Sign bit: always 0.
- Timestamp: milliseconds since custom epoch, e.g. `2026-01-01T00:00:00Z`.
- Worker ID: 0–1023, assigned by `SNOWFLAKE_WORKER_ID` env.
- Sequence: 0–4095 per millisecond per worker.

Capacity:

- 4096 IDs/ms/worker.
- 1024 workers.
- Timestamp lasts around 69 years from custom epoch.

## Integration points

Use generated IDs for:

- `users.id`
- `quiz_sets.id`
- `questions.id`
- `rooms.id`
- `matches.id`
- `answer_submissions.id`
- `outbox_events.id`
- domain event `event_id`
- WebSocket server `message_id`

This makes R11 clearly integrated, not a toy.

## Required source location

```text
backend/app/core/ids/
├── snowflake.py
└── README.md
```

## Pseudocode

```python
class SnowflakeGenerator:
    def __init__(self, worker_id: int, epoch_ms: int):
        assert 0 <= worker_id <= 1023
        self.worker_id = worker_id
        self.epoch_ms = epoch_ms
        self.sequence = 0
        self.last_ms = -1
        self.lock = threading.Lock()

    def next_id(self) -> int:
        with self.lock:
            now = current_time_ms()
            if now < self.last_ms:
                raise ClockMovedBackwardsError(self.last_ms - now)
            if now == self.last_ms:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    now = wait_until_next_ms(self.last_ms)
            else:
                self.sequence = 0
            self.last_ms = now
            return ((now - self.epoch_ms) << 22) | (self.worker_id << 12) | self.sequence
```

## Production caveats

- Worker IDs must be unique per API/worker replica. In Docker Compose, set `SNOWFLAKE_WORKER_ID=1` for api-a, `2` for api-b, `10` for outbox publisher, `20` for stream worker.
- If system clock moves backwards, fail fast and log an error rather than generating duplicate IDs.
- In tests, use deterministic fake clock.
- In Postgres, store as `BIGINT`.

## Tests

Minimum unit tests:

1. Generates positive int.
2. IDs are monotonic for one generator.
3. 5000 IDs in same test are unique.
4. Different worker IDs do not collide.
5. Clock rollback raises error.
6. Sequence overflow waits for next millisecond.

## Report explanation

Explain trade-offs:

- Pros: low latency, sortable IDs, no central DB sequence bottleneck, good for events.
- Cons: depends on clock monotonicity and unique worker IDs; not cryptographically random; exposes rough creation time.

## Alternative not chosen

UUIDv4 is simpler but not naturally sortable and does not demonstrate a from-scratch DDIA/System Design component as clearly. Database sequences are safe but centralize ID allocation and do not teach distributed ID generation.
