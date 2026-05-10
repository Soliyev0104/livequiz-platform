# Testing and Deployment

## Test layers

### Unit tests

- Snowflake ID generator.
- Scoring logic.
- Room code generator.
- Moderation keyword rules.
- WebSocket message validation.

### Integration tests

- Postgres migrations apply cleanly.
- Redis leaderboard updates.
- Answer submission transaction enforces uniqueness.
- Outbox publisher marks events published.
- Stream worker writes to ClickHouse.

### End-to-end tests

- Host creates quiz → opens room → player joins → host starts → player answers → leaderboard updates → match finishes → analytics visible.
- Duplicate answer submission returns safe duplicate/idempotent response.
- Moderator handles report.

## Load/demo test script

Create `scripts/load-test-rooms.py`:

- Create one room.
- Join 50 simulated players.
- Submit answers for 10 questions.
- Print latency p50/p95 for join, answer, leaderboard.

## Manual demo checklist

1. `docker compose up -d --build` succeeds.
2. `make migrate && make seed` succeeds.
3. Open `/api/docs` and show Swagger.
4. Open frontend and login as host.
5. Create quiz or use seed quiz.
6. Create room and copy code.
7. Join from two browser tabs as players.
8. Start match.
9. Submit answers and show live leaderboard.
10. End match and show analytics.
11. Open Grafana and show trace/log/metric for answer submission.
12. Show Redpanda/ClickHouse data or logs from stream worker.

## Deployment on DigitalOcean

```bash
ssh root@YOUR_DROPLET_IP
apt update && apt install -y docker.io docker-compose-plugin git ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

git clone https://github.com/YOUR_ORG/livequiz.git
cd livequiz
cp env/.env.example .env
nano .env

docker compose up -d --build
make migrate
make seed
```

## Final submission package

The course asks for a zip containing:

```text
report.pdf
LINKS.txt
```

`LINKS.txt` should contain:

```text
Deployed URL: http://YOUR_DOMAIN_OR_IP
GitHub URL: https://github.com/YOUR_ORG/livequiz
Team roster:
- Name, Student ID, Role
- ...
```

Also tag the repository:

```bash
git tag v1.0
git push origin v1.0
```

## Known limitations to mention honestly

- Single-VM Docker Compose, not Kubernetes.
- Redpanda single broker in demo; production would use replication.
- Redis is single instance in demo.
- Basic rule-based moderation, not ML.
- WebSocket reconnect uses snapshot recovery, not full event replay.
