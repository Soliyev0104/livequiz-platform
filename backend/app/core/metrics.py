"""Domain-specific Prometheus metrics for the API process (P10).

Registered against the default ``prometheus_client`` registry — the same one
:class:`prometheus_fastapi_instrumentator.Instrumentator` serves at
``/metrics``. The HTTP request histogram / counter
(``http_request_duration_seconds``, ``http_requests_total``, …) come from the
instrumentator itself; everything here is gameplay-specific.

Cardinality rule: identifiers that fan out without bound — ``room_id``,
``match_id``, ``room_code`` — are NEVER labels here. They go into traces and
logs instead. The outbox publisher and stream worker run in their own
processes with their own registries; their gauges/counters
(``outbox_unpublished_total``, ``stream_worker_*``) are defined next to those
entrypoints.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

quiz_answer_submissions_total = Counter(
    "quiz_answer_submissions_total",
    "Accepted answer submissions, partitioned by correctness.",
    ["correct"],
)

quiz_answer_latency_ms = Histogram(
    "quiz_answer_latency_ms",
    "Player response time in milliseconds (question start → submission).",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000),
)

ws_connections_active = Gauge(
    "ws_connections_active",
    "Currently-open WebSocket connections served by this API replica.",
)


def record_answer_submission(*, is_correct: bool, response_time_ms: int) -> None:
    """Bump the answer counter + latency histogram for one accepted submit."""
    quiz_answer_submissions_total.labels(correct="true" if is_correct else "false").inc()
    quiz_answer_latency_ms.observe(max(0, int(response_time_ms)))
