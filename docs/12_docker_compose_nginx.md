# Docker Compose and Nginx

## Compose services

Use these containers:

- `nginx`
- `frontend`
- `api-a`
- `api-b`
- `postgres`
- `redis`
- `redpanda`
- `clickhouse`
- `outbox-publisher`
- `stream-worker`
- `otel-collector`
- `prometheus`
- `loki`
- `tempo`
- `grafana`

## Compose sketch

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./ops/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - frontend
      - api-a
      - api-b
    networks: [quiznet]

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_API_BASE: /api/v1
      NEXT_PUBLIC_WS_BASE: /ws
    networks: [quiznet]

  api-a: &api
    build: ./backend
    environment:
      SERVICE_NAME: api-a
      SNOWFLAKE_WORKER_ID: 1
      DATABASE_URL: postgresql+asyncpg://livequiz:livequiz@postgres:5432/livequiz
      REDIS_URL: redis://redis:6379/0
      REDPANDA_BOOTSTRAP_SERVERS: redpanda:9092
      CLICKHOUSE_URL: http://clickhouse:8123
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/ready"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks: [quiznet]

  api-b:
    <<: *api
    environment:
      SERVICE_NAME: api-b
      SNOWFLAKE_WORKER_ID: 2
      DATABASE_URL: postgresql+asyncpg://livequiz:livequiz@postgres:5432/livequiz
      REDIS_URL: redis://redis:6379/0
      REDPANDA_BOOTSTRAP_SERVERS: redpanda:9092
      CLICKHOUSE_URL: http://clickhouse:8123
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: livequiz
      POSTGRES_PASSWORD: livequiz
      POSTGRES_DB: livequiz
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U livequiz -d livequiz"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks: [quiznet]

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks: [quiznet]

  redpanda:
    image: redpandadata/redpanda:v24.2.9
    command:
      - redpanda
      - start
      - --overprovisioned
      - --smp=1
      - --memory=1G
      - --reserve-memory=0M
      - --node-id=0
      - --check=false
      - --kafka-addr=PLAINTEXT://0.0.0.0:9092
      - --advertise-kafka-addr=PLAINTEXT://redpanda:9092
    volumes:
      - redpandadata:/var/lib/redpanda/data
    networks: [quiznet]

  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    volumes:
      - clickhousedata:/var/lib/clickhouse
      - ./migrations/clickhouse:/docker-entrypoint-initdb.d:ro
    networks: [quiznet]

volumes:
  pgdata:
  redisdata:
  redpandadata:
  clickhousedata:

networks:
  quiznet:
    driver: bridge
```

## Nginx config sketch

```nginx
events {}

http {
  upstream api_backend {
    least_conn;
    server api-a:8000;
    server api-b:8000;
  }

  upstream frontend_backend {
    server frontend:3000;
  }

  map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
  }

  server {
    listen 80;

    location /api/ {
      proxy_pass http://api_backend/api/;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Request-ID $request_id;
    }

    location /ws/ {
      proxy_pass http://api_backend/ws/;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Host $host;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
    }

    location / {
      proxy_pass http://frontend_backend;
      proxy_set_header Host $host;
    }
  }
}
```

## Makefile targets

```makefile
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec api-a alembic upgrade head

seed:
	docker compose exec api-a python -m app.db.seed

clickhouse-migrate:
	docker compose exec clickhouse clickhouse-client --multiquery < migrations/clickhouse/001_events.sql

test:
	docker compose exec api-a pytest -q
```

## Production notes

- Use a domain and Certbot or Caddy/Traefik for TLS.
- Keep only Nginx public.
- Set strong JWT secrets in `.env`.
- Use `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
- Tag final GitHub version as `v1.0`.
