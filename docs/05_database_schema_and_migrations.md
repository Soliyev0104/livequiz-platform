# Database Schema and Migrations

## Postgres migration strategy

Use Alembic. Migrations must be committed and reproducible.

Commands:

```bash
make migrate      # alembic upgrade head
make seed         # seed users, quizzes, demo room
make db-reset     # drop volumes in dev only, recreate, migrate, seed
```

## Postgres extensions

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

Use `pg_trgm` for quiz search if not adding Elasticsearch/Meilisearch.

## Required indexes

```sql
-- Auth
CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email));

-- Quiz discovery
CREATE INDEX ix_quiz_sets_owner_created ON quiz_sets (owner_id, created_at DESC);
CREATE INDEX ix_quiz_sets_public_published ON quiz_sets (created_at DESC)
WHERE visibility = 'public' AND is_published = true;
CREATE INDEX ix_quiz_sets_title_trgm ON quiz_sets USING gin (title gin_trgm_ops);

-- Question ordering
CREATE UNIQUE INDEX ux_questions_quiz_position ON questions (quiz_set_id, position);
CREATE UNIQUE INDEX ux_answer_options_question_position ON answer_options (question_id, position);

-- Room flow
CREATE UNIQUE INDEX ux_rooms_code ON rooms (code);
CREATE INDEX ix_rooms_host_created ON rooms (host_id, created_at DESC);
CREATE UNIQUE INDEX ux_room_participant_nickname ON room_participants (room_id, lower(nickname));

-- Answer correctness and idempotency
CREATE UNIQUE INDEX ux_submission_once ON answer_submissions (match_question_id, participant_id);
CREATE UNIQUE INDEX ux_submission_request ON answer_submissions (request_id);
CREATE INDEX ix_submissions_match_participant ON answer_submissions (match_id, participant_id);

-- Leaderboard snapshot
CREATE UNIQUE INDEX ux_final_scores_match_participant ON final_scores (match_id, participant_id);
CREATE INDEX ix_final_scores_rank ON final_scores (match_id, rank);

-- Outbox polling
CREATE INDEX ix_outbox_unpublished ON outbox_events (occurred_at)
WHERE published_at IS NULL;
```

## Important constraints

- Room capacity must be checked in service layer with row lock on room or Redis admission lock.
- `answer_submissions` uniqueness enforces one answer per participant per match question.
- `room_participants(room_id, lower(nickname))` prevents nickname duplicates.
- Question options should be validated in service layer because SQL check across child rows is awkward.

## Transaction examples

### Answer submission transaction

1. Lock current match question row or validate against Redis current question version.
2. Check server deadline.
3. Insert `answer_submissions`; if unique violation, return original/duplicate answer response.
4. Insert `outbox_events` with `AnswerSubmitted` payload.
5. Commit.
6. After commit, update Redis leaderboard and publish WS event. If Redis fails, the next snapshot can be reconstructed from Postgres.

### Match end transaction

1. Set room and match status to completed.
2. Calculate final scores from `answer_submissions`.
3. Insert/update `final_scores`.
4. Insert `MatchFinished` outbox event.
5. Commit.
6. Broadcast `match.finished` through Redis pub/sub.

## ClickHouse schema

Create in `migrations/clickhouse/001_events.sql`:

```sql
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
```

Create in `migrations/clickhouse/002_analytics_views.sql`:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS livequiz.question_accuracy_mv
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (match_id, question_id)
AS
SELECT
    match_id,
    question_id,
    count() AS total_answers,
    sum(is_correct) AS correct_answers,
    sum(response_time_ms) AS response_time_sum_ms,
    occurred_at
FROM livequiz.answer_events
GROUP BY match_id, question_id, occurred_at;
```

## Seed data

Seed these users:

- `admin@livequiz.local` / admin
- `host@livequiz.local` / host
- `player1@livequiz.local` / player
- `player2@livequiz.local` / player

Seed at least three quiz sets:

1. Computer Networks basics.
2. Database design fundamentals.
3. General knowledge demo.

Each quiz should have 8–12 questions with answer options.
