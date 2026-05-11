-- LiveQuiz ClickHouse schema — raw events and per-type fact tables.
--
-- Loaded by clickhouse-server on first boot via the
-- /docker-entrypoint-initdb.d mount, and re-applied on demand by
-- `make clickhouse-migrate`. Every statement is idempotent so re-runs
-- are safe.

CREATE DATABASE IF NOT EXISTS livequiz;

CREATE TABLE IF NOT EXISTS livequiz.events_raw
(
    event_id UInt64,
    event_type LowCardinality(String),
    aggregate_type LowCardinality(String),
    aggregate_id UInt64,
    room_id Nullable(UInt64),
    match_id Nullable(UInt64),
    participant_id Nullable(UInt64),
    question_id Nullable(UInt64),
    occurred_at DateTime64(3, 'UTC'),
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (event_type, occurred_at, event_id);

CREATE TABLE IF NOT EXISTS livequiz.answer_events
(
    event_id UInt64,
    match_id UInt64,
    room_id UInt64,
    participant_id UInt64,
    question_id UInt64,
    is_correct UInt8,
    score_awarded Int32,
    response_time_ms UInt32,
    occurred_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (match_id, question_id, participant_id, event_id);
