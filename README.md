# LiveQuiz — Online Multiplayer Quiz Platform

LiveQuiz is a real-time multiplayer quiz platform designed for the Database Application and Design group project. It demonstrates a realistic distributed system: transactional quiz/room operations in Postgres, live gameplay over WebSockets, Redis for hot room state and caching, Redpanda/Kafka-compatible event streaming, ClickHouse analytics, Nginx gateway/load balancing, Docker Compose orchestration, and Grafana-based observability.

## One-command local run target

```bash
cp env/.env.example .env
docker compose up -d --build
make migrate
make seed
```

Production should expose only Nginx on ports 80/443. Internal services stay on the private Docker network.

## Requirement coverage

| Requirement | How LiveQuiz satisfies it                                                                                             |
|---|-----------------------------------------------------------------------------------------------------------------------|
| R1 Business scenario | Online multiplayer quiz platform: real-time rooms, leaderboard, post-match analytics, content moderation.             |
| R2 Diagrams | ER, system architecture, project structure, compose dependency graph, BPMN diagrams in `docs/diagrams/`.              |
| R3 Relational DBMS | Postgres + Alembic migrations + seed data.                                                                            |
| R4 REST API | FastAPI with OpenAPI/Swagger at `/api/docs`.                                                                          |
| R5 Polyglot persistence | Redis for live room state/cache/presence; ClickHouse for event analytics.                                             |
| R6 Optimization | Redis cache, Redis sorted-set leaderboards, Postgres indexes, ClickHouse analytics tables, measured before/after plan. |
| R7 Additional API style | WebSocket gameplay protocol at `/ws/rooms/{room_code}`.                                                               |
| R8 Gateway/load balancing | Nginx routes frontend/API/WS and load-balances two FastAPI replicas.                                                  |
| R9 Docker Compose | Single `docker-compose.yml`, health checks, named volumes, one public gateway port.                                   |
| R10 Pipeline | Redpanda event stream + `stream-worker` writing analytics/events to ClickHouse; BPMN included.                        |
| R11 From-scratch component | Snowflake-style ID generator in `backend/app/core/ids/`, integrated for rooms, matches, submissions, events.          |
| R12 Observability | OpenTelemetry traces, Prometheus metrics, Loki logs, Tempo traces, Grafana dashboards.                                |
| R13 Documentation | Root README, API docs, CHANGELOG, contributor guide, docs folder.                                                     |

## Recommended repository name

Use `livequiz` or `livequiz-platform`. The docs assume `livequiz-platform` as the root folder.

## Build order

1. Docker base + Postgres + Redis + Nginx + frontend hello page.
2. FastAPI app, health endpoints, DB connection, Alembic.
3. Auth + roles + quiz/question CRUD.
4. Room creation/join flow.
5. WebSocket room protocol.
6. Answer submission + scoring + live leaderboard.
7. Transactional outbox + Redpanda + stream worker + ClickHouse analytics.
8. Content moderation queue.
9. Observability dashboards.
10. Production deployment + report screenshots.
