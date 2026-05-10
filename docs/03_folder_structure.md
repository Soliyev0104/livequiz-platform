# Project Folder Structure

Use one monorepo. It is easier for Docker Compose, team review, and report diagrams.

```text
livequiz-platform/
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── Makefile
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
├── docs/
│   ├── 00_START_HERE_FOR_AI.md
│   ├── 01_product_requirements.md
│   ├── 02_architecture.md
│   ├── 03_folder_structure.md
│   ├── 04_domain_model_dbml.md
│   ├── 05_database_schema_and_migrations.md
│   ├── 06_api_contracts.md
│   ├── 07_websocket_protocol.md
│   ├── 08_streaming_pipeline_and_bpmn.md
│   ├── 09_caching_indexing_optimization.md
│   ├── 10_from_scratch_component_snowflake.md
│   ├── 11_observability.md
│   ├── 12_docker_compose_nginx.md
│   ├── 13_frontend_ui_ux.md
│   ├── 14_testing_deployment.md
│   ├── 15_report_outline.md
│   ├── 16_ai_coding_prompts.md
│   ├── 17_team_task_split.md
│   └── diagrams/
│       ├── system_architecture.mmd
│       ├── er_diagram.mmd
│       ├── compose_dependency_graph.mmd
│       ├── bpmn_match_flow.mmd
│       └── bpmn_event_pipeline.mmd
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── v1/
│   │   │       ├── auth.py
│   │   │       ├── users.py
│   │   │       ├── quiz_sets.py
│   │   │       ├── rooms.py
│   │   │       ├── matches.py
│   │   │       ├── analytics.py
│   │   │       └── moderation.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   ├── logging.py
│   │   │   ├── telemetry.py
│   │   │   └── ids/
│   │   │       ├── snowflake.py
│   │   │       └── README.md
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── base.py
│   │   │   └── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── quiz_service.py
│   │   │   ├── room_service.py
│   │   │   ├── scoring_service.py
│   │   │   ├── moderation_service.py
│   │   │   ├── outbox_service.py
│   │   │   └── analytics_service.py
│   │   ├── repositories/
│   │   ├── ws/
│   │   │   ├── router.py
│   │   │   ├── connection_manager.py
│   │   │   ├── messages.py
│   │   │   └── redis_pubsub.py
│   │   ├── cache/
│   │   │   ├── redis.py
│   │   │   ├── keys.py
│   │   │   ├── leaderboard.py
│   │   │   └── idempotency.py
│   │   └── events/
│   │       ├── envelope.py
│   │       ├── topics.py
│   │       └── types.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   ├── quiz-builder/
│   │   │   ├── room-lobby/
│   │   │   ├── live-match/
│   │   │   ├── analytics/
│   │   │   └── moderation/
│   │   ├── lib/
│   │   │   ├── api-client.ts
│   │   │   ├── ws-client.ts
│   │   │   └── types.ts
│   │   └── styles/
├── workers/
│   ├── outbox_publisher/
│   │   ├── Dockerfile
│   │   └── app/
│   ├── stream_worker/
│   │   ├── Dockerfile
│   │   └── app/
│   └── scheduler/
│       ├── Dockerfile
│       └── app/
├── migrations/
│   ├── clickhouse/
│   │   ├── 001_events.sql
│   │   └── 002_analytics_views.sql
│   └── seeds/
│       ├── seed_users.py
│       ├── seed_quizzes.py
│       └── seed_demo_room.py
├── ops/
│   ├── nginx/
│   │   ├── nginx.conf
│   │   └── prod.conf
│   ├── observability/
│   │   ├── otel-collector.yaml
│   │   ├── prometheus.yml
│   │   ├── promtail.yml
│   │   ├── loki.yml
│   │   ├── tempo.yml
│   │   └── grafana/
│   └── scripts/
│       ├── wait-for-it.sh
│       ├── create-redpanda-topics.sh
│       └── backup-postgres.sh
└── scripts/
    ├── dev-reset.sh
    ├── load-test-rooms.py
    └── export-report-screenshots.md
```

## Why this structure is senior-friendly

- `backend/app/services` contains business logic; routers stay thin.
- `repositories` isolate persistence queries.
- `events` gives one canonical domain-event contract.
- `workers` are separate deployable services, not hidden background threads in the API container.
- `ops` keeps gateway and observability configs versioned.
- `migrations/clickhouse` makes the analytics store reproducible.
