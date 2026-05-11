# LiveQuiz backend

FastAPI + async SQLAlchemy 2.0 + Pydantic v2.

## Local dev

```bash
# from repo root
docker compose up -d --build api-a api-b
curl http://localhost/api/v1/health
curl http://localhost/api/v1/ready
```

## Layout

```
app/
  main.py            FastAPI factory + lifespan
  api/v1/            REST routers (filled per phase)
  core/              config, security, logging, telemetry, ids/
  db/                sessions, declarative base, ORM models
  schemas/           Pydantic request/response models
  services/          business logic
  repositories/      persistence queries
  ws/                WebSocket protocol (P06)
  cache/             Redis helpers (P05)
  events/            domain event envelope (P08)
tests/
  unit/ integration/ e2e/
```

## Match scheduler (P07) — known limitation

The match service spawns one in-process `asyncio.Task` per active
question (`arm_question` / `close_question`) and one per inter-question
gap. The `MatchScheduler` keeps the active task per match so
`pause_match` can cancel it. This works for the demo's ~50 concurrent
match ceiling; in production we would split scheduling out into a
dedicated worker (Temporal, a Postgres-backed scheduled-jobs queue, or
Redis-keyspace-notifications-driven timers) so a replica restart never
loses an in-flight deadline. On startup `recover_running_matches`
re-arms any timer it can find for matches still flagged `running`,
which mitigates but does not eliminate the loss window.
