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
| R1 Business scenario | Online multiplayer quiz platform: real-time rooms, leaderboard, post-match analytics, content moderation; see `docs/01_product_requirements.md`. |
| R2 Diagrams | ER, system architecture, project structure, compose dependency graph, BPMN diagrams in `docs/diagrams/`. |
| R3 Relational DBMS | Postgres models in `backend/app/db/models/`, Alembic baseline in `backend/alembic/versions/0001_baseline.py`, seed data in `migrations/seeds/`. |
| R4 REST API | FastAPI routers in `backend/app/api/v1/` and `backend/app/main.py`; Swagger at `/api/docs`, ReDoc at `/api/redoc`. |
| R5 Polyglot persistence | Redis cache/live state in `backend/app/cache/`; ClickHouse migrations in `migrations/clickhouse/`. |
| R6 Optimization | Redis list cache, sorted-set leaderboards, Postgres indexes, ClickHouse analytics, and measurements in `scripts/measurements/`. |
| R7 Additional API style | WebSocket gameplay protocol at `/ws/rooms/{room_code}` in `backend/app/ws/router.py`, documented in `docs/07_websocket_protocol.md`. |
| R8 Gateway/load balancing | Nginx routes frontend/API/WS and load-balances two FastAPI replicas via `ops/nginx/nginx.conf` and `ops/nginx/prod.conf`. |
| R9 Docker Compose | `docker-compose.yml` plus `docker-compose.prod.yml`, health checks, named volumes, one public gateway port. |
| R10 Pipeline | Redpanda event stream + `workers/outbox_publisher/` + `workers/stream_worker/`; BPMN in `docs/08_streaming_pipeline_and_bpmn.md`. |
| R11 From-scratch component | Snowflake-style ID generator in `backend/app/core/ids/`, integrated for users, rooms, matches, submissions, and events. |
| R12 Observability | OpenTelemetry in `backend/app/core/telemetry.py`, Prometheus metrics, Loki, Tempo, and Grafana dashboards in `ops/observability/`. |
| R13 Documentation | Root README, `docs/deployment.md`, `CHANGELOG.md`, `LINKS.txt`, `CONTRIBUTING.md`, and report screenshot procedure. |

## Demo credentials

Seed users from `migrations/seeds/seed_users.py`:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@livequiz.local` | `admin` |
| Host | `host@livequiz.local` | `host` |
| Player 1 | `player1@livequiz.local` | `player` |
| Player 2 | `player2@livequiz.local` | `player` |

Seed content includes the published quiz `Computer Networks basics` and demo room `DEMO01`.

## Known limitations

- Single-VM Docker Compose deployment, not Kubernetes or multi-region.
- One Redpanda broker and one Redis instance in the submission stack.
- Rule-based moderation rather than ML-assisted moderation.
- WebSocket recovery uses room snapshots and current-question state, not full event replay.

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
