# Report Screenshot Procedure

Create output folders:

```bash
mkdir -p docs/diagrams/png report_assets
```

## Diagrams

Render all Mermaid diagrams:

```bash
npx -y @mermaid-js/mermaid-cli \
  -i docs/diagrams/system_architecture.mmd \
  -o docs/diagrams/png/system_architecture.png \
  -b transparent
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/er_diagram.mmd -o docs/diagrams/png/er_diagram.png -b transparent
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/compose_dependency_graph.mmd -o docs/diagrams/png/compose_dependency_graph.png -b transparent
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/bpmn_match_flow.mmd -o docs/diagrams/png/bpmn_match_flow.png -b transparent
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/bpmn_event_pipeline.mmd -o docs/diagrams/png/bpmn_event_pipeline.png -b transparent
```

## API Docs

- Swagger: `http://localhost:8888/api/docs` -> `report_assets/swagger.png`
- ReDoc: `http://localhost:8888/api/redoc` -> `report_assets/redoc.png`

## Application Flow

- Host UI mid-match: open `http://localhost:8888/`, log in as `host@livequiz.local` / `host`, start a room -> `report_assets/host_mid_match.png`
- Player question screen: incognito/private window, join the room as a guest -> `report_assets/player_question.png`
- Final leaderboard: finish the match -> `report_assets/final_leaderboard.png`
- Analytics: open the frontend analytics page or `GET /api/v1/matches/{id}/analytics` -> `report_assets/analytics.png`

## Observability

- Grafana: `http://localhost:3001/`, open the LiveQuiz dashboard and capture API latency and WebSocket connections panels -> `report_assets/grafana_livequiz.png`
- Tempo: Grafana Explore -> Tempo -> search for `POST /api/v1/matches/{match_id}/answers`; capture the `leaderboard.update` span subtree -> `report_assets/tempo_answer_trace.png`
- Loki: Grafana Explore -> Loki query:

```logql
{container=~"livequiz.*api.*"} | json | request_id="<id>"
```

Save as `report_assets/loki_request_id.png`.

## ClickHouse Counts

Confirm data landed in the raw and answer fact tables:

```bash
docker compose exec clickhouse clickhouse-client -q "SELECT count() FROM livequiz.events_raw"
docker compose exec clickhouse clickhouse-client -q "SELECT count() FROM livequiz.answer_events"
```

Capture the terminal or paste the results into the report as the ClickHouse evidence.
