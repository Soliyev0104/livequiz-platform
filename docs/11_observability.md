# Observability

## Stack

- OpenTelemetry SDK in FastAPI and workers.
- OpenTelemetry Collector receives traces/metrics/logs.
- Tempo stores traces.
- Prometheus stores metrics.
- Loki stores structured logs.
- Grafana visualizes all three.

## Required screenshots for report

1. A trace for `POST /api/v1/matches/{match_id}/answers` showing API span, Postgres span, Redis leaderboard span, and outbox insert span.
2. A Loki log query filtered by `request_id` or `trace_id` showing the same answer submission.
3. A Prometheus/Grafana metric graph for request latency or WebSocket connections during a match.

## FastAPI instrumentation

Add:

- `opentelemetry-instrumentation-fastapi`
- `opentelemetry-instrumentation-sqlalchemy`
- `opentelemetry-instrumentation-redis`
- `prometheus-fastapi-instrumentator`
- JSON logging with `trace_id`, `span_id`, `request_id`, `user_id`, `room_code` where available.

## Metrics to expose

| Metric | Type | Labels |
|---|---|---|
| `http_request_duration_seconds` | histogram | method, route, status |
| `ws_connections_active` | gauge | room_code optional/hashed |
| `quiz_answer_submissions_total` | counter | correct, route |
| `quiz_answer_latency_ms` | histogram | match_id optional/hashed |
| `room_players_active` | gauge | room_code optional/hashed |
| `outbox_unpublished_total` | gauge | none |
| `stream_worker_events_processed_total` | counter | event_type |
| `stream_worker_event_lag_seconds` | gauge | topic |
| `redis_operation_errors_total` | counter | operation |

Avoid high-cardinality public labels in Prometheus. For report demo, room/match IDs may be shown in logs/traces, not necessarily metrics.

## Logging standard

Every log line should be JSON:

```json
{
  "timestamp": "2026-05-10T10:22:06.700Z",
  "level": "INFO",
  "service": "api",
  "message": "answer accepted",
  "request_id": "req_123",
  "trace_id": "...",
  "user_id": "738...",
  "room_code": "K7Q2M9",
  "match_id": "738..."
}
```

## Dashboards

Create Grafana dashboard panels:

- API requests per second.
- API p95 latency.
- Active WebSocket connections.
- Answer submissions per second.
- Outbox backlog.
- Stream worker lag.
- Redis memory and commands/sec.
- Postgres connections.
- ClickHouse inserts/sec.

## Alert-like checks for demo

Even if not implementing real alerts, show these thresholds in docs/report:

- Outbox unpublished > 100 for 5 minutes.
- API p95 > 500 ms for 5 minutes.
- Stream worker lag > 60 seconds.
- Redis unavailable.
