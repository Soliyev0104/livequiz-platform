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
