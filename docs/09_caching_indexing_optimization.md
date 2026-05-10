# Caching, Indexing, and Optimization

## Required optimization story for the report

The report needs at least one quantitative before/after comparison. Use these measurable cases:

### Measurement A — Leaderboard read path

Before: compute leaderboard with SQL aggregation over `answer_submissions` for every request.

After: update Redis sorted set on each accepted answer and read top N using `ZREVRANGE`.

Expected measurement:

```text
GET /matches/{id}/leaderboard top 10, 50 players, 10 questions
Before Postgres aggregation p95: ~40–120 ms local
After Redis sorted set p95: ~2–8 ms local
```

### Measurement B — Quiz search

Before: `ILIKE '%network%'` sequential scan.

After: `pg_trgm` GIN index on `quiz_sets.title`.

Expected measurement:

```sql
EXPLAIN ANALYZE SELECT * FROM quiz_sets WHERE title ILIKE '%network%' LIMIT 20;
```

Compare planning/execution time and scan type.

### Measurement C — Analytics

Before: Postgres joins over answer submissions.

After: ClickHouse `answer_events` and materialized views.

Expected measurement:

```text
Question accuracy report for 10k answer events
Before Postgres OLTP query: ~100–500 ms
After ClickHouse aggregate: ~5–50 ms
```

## Redis key design

```text
room:{code}:state                         hash/json, TTL 24h after completion
room:{code}:presence                      set, TTL via heartbeat keys
room:{code}:participants                  hash participant_id -> nickname
match:{match_id}:leaderboard              sorted set score by participant_id
match:{match_id}:answered:{question_id}   set participant_id
ws:room:{code}                            pub/sub channel
cache:quiz:{quiz_id}:v{version}           json, TTL 10m
cache:quiz:list:{hash_of_query}           json, TTL 60s
idem:{request_id}                         json response, TTL 24h
rate:{actor}:{action}:{window}            token bucket state, TTL window
```

## Cache invalidation

- Quiz set cache key includes `version`; updating quiz increments version, so old cache naturally expires.
- Room state keys expire after room completion.
- Leaderboard Redis data is authoritative only during live match; final leaderboard is persisted to Postgres.
- Idempotency keys expire after 24 hours.

## Postgres indexing plan

See `docs/05_database_schema_and_migrations.md` for SQL. Focus on:

- Uniqueness constraints for correctness.
- Partial indexes for public/published quiz discovery.
- Trigram index for search.
- Outbox unpublished partial index for fast polling.

## Query tuning process

1. Seed demo data with 10k submissions.
2. Run `EXPLAIN ANALYZE` before indexes/cache.
3. Add index/cache/materialized path.
4. Run same query 5–10 times.
5. Capture p50/p95 or best representative before/after.
6. Put screenshots/numbers in report.

## Storage optimization

- ClickHouse partitions by month and orders by match/question IDs.
- Store high-volume events in ClickHouse, not Postgres JSON blobs.
- Keep Postgres JSONB only for low-volume flexible settings and event payloads.
- Use Redis TTLs so hot-state memory is bounded.

## Rate limiting

Use simple Redis-backed rate limiting for public actions:

- `/rooms/{code}/join`: IP + room code.
- `answer.submit`: participant + match question.
- auth login: IP + email hash.
- WebSocket messages: connection ID.

This can be implemented separately from the R11 Snowflake component; do not make it too complex unless there is time.
