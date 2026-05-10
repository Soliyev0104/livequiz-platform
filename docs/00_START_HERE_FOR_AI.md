# START HERE FOR AI CODING AGENTS

You are building `livequiz_platform`, an online multiplayer quiz platform for a DAD distributed-systems project. Do not collapse it into a single FastAPI + Postgres CRUD app. The grading requires multi-service architecture, polyglot persistence, non-REST API style, Docker Compose, pipeline, from-scratch system component, and observability.

## Non-negotiable architecture

- Backend framework: FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2.
- OLTP database: Postgres.
- Hot state/cache/pubsub: Redis.
- Event broker: Redpanda, using Kafka-compatible APIs.
- Analytics store: ClickHouse.
- Gateway: Nginx, one public entrypoint, routes frontend, REST, and WebSocket.
- Frontend: Next.js or Vite React + TypeScript + Tailwind + shadcn-style UI.
- Observability: OpenTelemetry instrumentation, Prometheus metrics, Loki logs, Tempo traces, Grafana dashboards.
- From-scratch component: Snowflake-style ID generator integrated into real DB records and emitted events.

## Main system idea

Postgres is the source of truth for users, quiz content, rooms, matches, questions, submissions, final results, moderation reports, and the outbox. Redis stores low-latency live-room state: presence, current question snapshot, leaderboard sorted sets, answer idempotency windows, and pub/sub messages for WebSocket replicas. Redpanda carries immutable domain events from the transactional outbox to analytics. ClickHouse stores high-volume event facts and post-match metrics.

## Critical implementation rule

Use the transactional outbox pattern. When an important state change happens in Postgres, insert the domain event into `outbox_events` in the same transaction. A worker reads unpublished outbox rows, publishes to Redpanda, marks them published, and consumers write analytics to ClickHouse. Do not write DB state first and then directly publish to the broker from request code without an outbox.

## Coding sequence for agents

1. Create repo structure exactly as in `docs/03_folder_structure.md`.
2. Implement Docker Compose and health checks from `docs/12_docker_compose_nginx.md`.
3. Implement migrations using `docs/05_database_schema_and_migrations.md` and DBML from `docs/04_domain_model_dbml.md`.
4. Implement REST contracts from `docs/06_api_contracts.md`.
5. Implement WebSocket protocol from `docs/07_websocket_protocol.md`.
6. Implement event pipeline from `docs/08_streaming_pipeline_and_bpmn.md`.
7. Implement Snowflake generator from `docs/10_from_scratch_component_snowflake.md`.
8. Implement frontend according to `docs/13_frontend_ui_ux.md`.
9. Add tests and deployment steps from `docs/14_testing_deployment.md`.

## What not to do

- Do not auto-generate the ERD from ORM and call it final.
- Do not store all live room state only in Postgres; Redis must be used meaningfully.
- Do not fake WebSocket by polling.
- Do not fake analytics by querying Postgres only; write events to ClickHouse through the stream worker.
- Do not add backend code nobody can explain. Keep patterns explicit and documented.
