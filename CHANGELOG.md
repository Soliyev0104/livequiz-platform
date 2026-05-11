# Changelog

## P12 - Hardening

- Added remaining rate limits for REST answers, host WebSocket messages, and reports, with `Retry-After` on 429 envelopes.
- Added Nginx CSP and Permissions-Policy headers; kept the stronger existing HSTS value `max-age=63072000; includeSubDomains; preload`.
- Added admin-only `GET /api/v1/admin/metrics`.
- Polished OpenAPI with shared `ErrorResponse`, router-level error responses, ReDoc at `/api/redoc`, and focused request/response examples.
- Added integration coverage for documented error codes and public idempotent answer retry behavior.
- Added `LEADERBOARD_BACKEND=pg` before-mode support plus `scripts/load-test-rooms.py` and leaderboard measurement output.
- Added deployment guide, README submission sections, `LINKS.txt`, and the report screenshot procedure.

## P11 - Observability

- Added OpenTelemetry tracing, Prometheus metrics, Loki logs, Tempo traces, and Grafana provisioning under `ops/observability/`.
- Correlated request IDs through middleware, Nginx, logs, and trace attributes.

## P10 - From-Scratch Component

- Implemented the Snowflake-style ID generator in `backend/app/core/ids/`.
- Integrated generated IDs across users, quizzes, rooms, matches, submissions, outbox events, and snapshots.

## P09 - Caching And Optimization

- Added Redis list caching for quiz search and Redis sorted-set live leaderboards.
- Added search/leaderboard measurement scripts and before/after documentation.

## P08 - Streaming And Analytics

- Added transactional outbox publishing to Redpanda.
- Added stream worker ingestion into ClickHouse tables and match analytics endpoints.

## P07 - Match Runtime

- Added host match controls, scheduled question lifecycle, answer submission, scoring, idempotency, and final leaderboard snapshots.

## P06 - WebSocket Protocol

- Added `/ws/rooms/{code}` for room snapshots, presence, heartbeat, answer messages, and live leaderboard broadcasts.

## P05 - Rooms

- Added room creation, join, capacity admission, nickname uniqueness, participant tokens, and Redis room snapshots.

## P04 - Quiz CRUD

- Added quiz set and question CRUD, publish validation, public/owner visibility, and quiz search.

## P03 - Auth And Roles

- Added registration, login, refresh, logout, role guards, JWT revocation, and audit logging.

## P02 - Database

- Added relational schema, SQLAlchemy models, Alembic baseline, and seed data.

## P01 - API Skeleton

- Added FastAPI app structure, health/readiness endpoints, error envelope, middleware, and test harness.

## P00 - Project Foundation

- Added repository structure, Docker Compose stack, Nginx gateway, frontend shell, and planning docs.
