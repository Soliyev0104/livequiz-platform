# Streaming Pipeline and BPMN

## Why a stream pipeline fits this project

Live quiz gameplay emits many small events: player joined, question started, answer submitted, leaderboard changed, match finished, report created. These events are valuable for post-match analytics, monitoring, and moderation. A broker decouples gameplay latency from analytical writes.

## Event flow

```mermaid
sequenceDiagram
    participant API as FastAPI
    participant PG as Postgres
    participant OP as Outbox Publisher
    participant RP as Redpanda
    participant SW as Stream Worker
    participant CH as ClickHouse
    API->>PG: business transaction + insert outbox_events
    OP->>PG: poll unpublished events
    OP->>RP: publish event envelope
    OP->>PG: mark published_at
    SW->>RP: consume event
    SW->>CH: insert event facts / analytics
```

## Domain event envelope

```json
{
  "event_id": "738511559401627648",
  "event_type": "AnswerSubmitted",
  "aggregate_type": "match",
  "aggregate_id": "738511500123456789",
  "occurred_at": "2026-05-10T10:22:06.700Z",
  "producer": "livequiz-api",
  "schema_version": 1,
  "payload": {
    "room_id": "738511241389260800",
    "match_id": "738511500123456789",
    "match_question_id": "738511555098206208",
    "question_id": "738511553000000001",
    "participant_id": "738511300977209344",
    "is_correct": true,
    "score_awarded": 915,
    "response_time_ms": 1700
  }
}
```

## Topics

| Topic                         | Events | Consumer |
|-------------------------------|---|---|
| `livequiz.events.room`        | RoomCreated, PlayerJoined, PlayerLeft | stream-worker |
| `livequiz.events.match`       | MatchStarted, QuestionStarted, QuestionClosed, MatchFinished | stream-worker |
| `livequiz.events.answer`      | AnswerSubmitted | stream-worker |
| `livequiz.events.moderation`  | ContentReported, ContentFlagged, ModerationDecisionMade | stream-worker |
| `livequiz.events.dead_letter` | Failed events | manual/admin review |

## Outbox publisher algorithm

1. Select up to 100 unpublished `outbox_events` rows ordered by `occurred_at` with `FOR UPDATE SKIP LOCKED`.
2. Publish each event to Redpanda topic chosen by event type.
3. Mark `published_at = now()` after broker ack.
4. Increment `publish_attempts` on failure.
5. Move to dead-letter topic after max attempts or invalid schema.

## Stream worker algorithm

1. Consume events with consumer group `livequiz-analytics-v1`.
2. Validate envelope schema version.
3. Deduplicate using `event_id` cache and ClickHouse replacing table.
4. Insert raw event into `events_raw`.
5. For `AnswerSubmitted`, insert into `answer_events`.
6. For `MatchFinished`, compute final analytics snapshot and optional cache warming.
7. Commit broker offset only after successful processing.

## BPMN — Live match workflow

```mermaid
flowchart TD
    Start((Start)) --> CreateRoom[Host creates room]
    CreateRoom --> Lobby[Players join lobby]
    Lobby --> StartMatch[Host starts match]
    StartMatch --> QStart[Server starts question]
    QStart --> Timer{Deadline reached?}
    Timer -->|No| Answer[Players submit answers]
    Answer --> Validate[Validate deadline and uniqueness]
    Validate --> Score[Score answer]
    Score --> Broadcast[Broadcast leaderboard]
    Broadcast --> Timer
    Timer -->|Yes| CloseQ[Close question and reveal answer]
    CloseQ --> MoreQ{More questions?}
    MoreQ -->|Yes| QStart
    MoreQ -->|No| Finalize[Finalize scores]
    Finalize --> Emit[Emit MatchFinished event]
    Emit --> End((End))
```

## BPMN — Event analytics pipeline

```mermaid
flowchart TD
    Start((Start)) --> Tx[API commits transaction with outbox row]
    Tx --> Poll[Outbox publisher polls unpublished rows]
    Poll --> Publish[Publish event to Redpanda]
    Publish --> Mark[Mark outbox row published]
    Publish --> Consume[Stream worker consumes event]
    Consume --> Validate[Validate schema and dedupe event_id]
    Validate --> Raw[Insert raw event to ClickHouse]
    Raw --> Type{Event type}
    Type -->|AnswerSubmitted| AnswerFact[Insert answer_events fact]
    Type -->|MatchFinished| MatchAgg[Build match analytics snapshot]
    Type -->|Moderation| ModAgg[Update moderation metrics]
    AnswerFact --> Commit[Commit consumer offset]
    MatchAgg --> Commit
    ModAgg --> Commit
    Commit --> End((End))
```

## BPMN — Moderation workflow

```mermaid
flowchart TD
    Start((Start)) --> Content[Nickname/question/report created]
    Content --> RuleCheck[Rule-based text moderation]
    RuleCheck --> Suspicious{Suspicious?}
    Suspicious -->|No| Allow[Allow content]
    Suspicious -->|Yes| Flag[Create moderation report]
    Flag --> Queue[Moderator queue]
    Queue --> Review[Moderator reviews context]
    Review --> Decision{Decision}
    Decision -->|Dismiss| Dismiss[Mark dismissed]
    Decision -->|Hide| Hide[Hide content]
    Decision -->|Mute/Ban| Ban[Apply user action]
    Dismiss --> Audit[Write audit log]
    Hide --> Audit
    Ban --> Audit
    Audit --> End((End))
```

## Failure handling

- If Redpanda is temporarily down, outbox rows remain unpublished and publisher retries.
- If ClickHouse is down, stream worker stops committing offsets and resumes later.
- If an event is malformed, write to dead-letter topic and log trace ID.
- If duplicate event arrives, consumer ignores it by `event_id`.
