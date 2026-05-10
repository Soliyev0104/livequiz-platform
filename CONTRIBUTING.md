# Contributing Guide

## Branch workflow

1. Create a branch from `main`.
2. Keep PRs small and vertical.
3. Add or update tests.
4. Update docs if API/DB/event contracts change.
5. Run `make test` before merging.

## Commit style

Use clear commits:

```text
feat(rooms): add room join endpoint
fix(scoring): prevent duplicate answer scoring
docs(report): add pipeline BPMN
```

## Backend rules

- Routers are thin.
- Business logic lives in services.
- Persistence queries live in repositories.
- Important mutations insert outbox events.
- Never commit secrets.

## Frontend rules

- Keep API types synchronized with backend schemas.
- Handle WebSocket reconnect.
- Show loading/error states.
- Keep UI accessible.
