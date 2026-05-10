# Smart Team Task Split

Do not split as “one frontend person, one backend person, one tester.” Each person should own a vertical slice with DB/API/UI/tests/docs where possible. This creates balanced Git history and avoids merge conflicts.

## For a 5-person team

### Member A — Auth + user/role foundation

- User models, auth endpoints, JWT, role guards.
- Frontend auth pages.
- Auth tests.
- Report section: security and auth flow.

### Member B — Quiz content vertical

- Quiz sets, questions, options, tags, publish validation.
- Quiz builder UI.
- Quiz search indexing measurement.
- Report section: domain model and relational schema.

### Member C — Live room vertical

- Room creation/join, Redis room state, WebSocket connection manager.
- Host lobby and player lobby UI.
- WS tests and reconnect behavior.
- Report section: WebSocket protocol rationale.

### Member D — Match/scoring/leaderboard vertical

- Match start/end, question timing, answer submission, scoring.
- Redis sorted-set leaderboard.
- Live match UI.
- Optimization measurement: SQL leaderboard vs Redis leaderboard.

### Member E — Pipeline/analytics/observability/deployment

- Outbox publisher, Redpanda, stream worker, ClickHouse.
- Analytics UI.
- OTel/Grafana stack.
- Docker Compose/Nginx/DigitalOcean deployment.
- Report sections: pipeline, observability, deployment.

## Shared rules

- Everyone writes tests for their slice.
- Everyone commits from their own GitHub account.
- Use feature branches and small PRs.
- Keep migrations coordinated: one person reviews migration conflicts.
- Update docs when changing contracts.

## Suggested branch names

```text
feature/auth-foundation
feature/quiz-builder
feature/live-rooms-ws
feature/match-scoring
feature/event-analytics
feature/frontend-polish
feature/observability
feature/deployment
```
