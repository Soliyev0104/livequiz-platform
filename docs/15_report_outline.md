# PDF Report Outline

Target: 10–15 pages, single column.

## 1. Cover page

- Team name: Avengers.
- Motto: “Real-time learning, measurable results.”
- Member list with student IDs and roles.
- GitHub URL.
- Deployed URL.
- Date.

## 2. Abstract

Half-page summary: online multiplayer quiz platform with FastAPI, Postgres, Redis, Redpanda, ClickHouse, WebSockets, Nginx, Docker Compose, Snowflake IDs, and Grafana observability.

## 3. Business Requirements

Use `docs/01_product_requirements.md`. Include at least five use cases and non-functional targets.

## 4. Domain Model and ER Diagram

Use DBML and Mermaid ERD from `docs/04_domain_model_dbml.md` and `docs/diagrams/er_diagram.mmd`. Include table inventory.

## 5. System Architecture

Use diagram from `docs/diagrams/system_architecture.mmd`. Explain every service and data store.

## 6. API Design

- REST endpoint table from `docs/06_api_contracts.md`.
- WebSocket rationale and message examples from `docs/07_websocket_protocol.md`.
- Mention OpenAPI URL.

## 7. Data-Layer Design

- Postgres schema and constraints.
- Redis data-model fit.
- ClickHouse analytics fit.
- Indexing/caching strategy.
- Before/after measurements.

## 8. Pipeline

- Transactional outbox.
- Redpanda event broker.
- Stream worker.
- ClickHouse analytics.
- BPMN diagrams.

## 9. From-Scratch Component

Snowflake ID generator:

- Bit layout.
- Why chosen.
- Integration points.
- Trade-offs and limitations.
- Tests.

## 10. Infrastructure and Deployment

- Docker Compose topology.
- Nginx gateway and load balancing.
- Health checks and volumes.
- DigitalOcean deployment.

## 11. Observability

- OTel instrumentation.
- Grafana screenshots: trace, log query, metric graph.
- Explain one correlated user action: answer submission.

## 12. Testing and Known Limitations

- Unit/integration/e2e/load tests.
- Known limitations from `docs/14_testing_deployment.md`.

## 13. Team Contribution Table

Example:

| Member | Main ownership | Secondary work | Approx. commit share |
|---|---|---|---|
| A | Auth + users | tests | 20% |
| B | Quiz builder + DB | report diagrams | 20% |
| C | Rooms + WebSockets | Redis | 20% |
| D | Pipeline + ClickHouse | observability | 20% |
| E | Frontend + UI | deployment | 20% |

Do not split as “frontend-only/backend-only/test-only”; each member should own a vertical slice where possible.

## 14. References

- Course project specification.
- Homework 3 architecture ideas: FastAPI, WebSocket, gRPC/API gateway, Redis, Docker Compose.
- Homework 4 Lambda/streaming architecture ideas: Kafka/stream, raw/analytics stores, serving API.
- Designing Data-Intensive Applications.
- System Design Interview.
