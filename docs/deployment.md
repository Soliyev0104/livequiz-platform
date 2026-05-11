# Deployment Guide

Target: one Ubuntu DigitalOcean droplet running Docker Compose behind Nginx.

## 1. Provision

Create an Ubuntu droplet, SSH in, then install Docker and firewall basics:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git make ufw
sudo systemctl enable --now docker
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 2. Configure

```bash
git clone <repository-url> livequiz-platform
cd livequiz-platform
cp env/.env.example .env
```

Edit `.env` for production:

- `APP_ENV=prod`
- strong `JWT_SECRET` and `JWT_REFRESH_SECRET` (`openssl rand -hex 32`)
- public `CORS_ORIGINS` (`http://DROPLET_IP` for IP-only, `https://yourdomain` for TLS)
- `NGINX_CONF=prod.conf` for an IP-only HTTP demo, or `NGINX_CONF=prod.tls.conf` for direct HTTPS
- `NGINX_PORT=80`; for TLS also keep `NGINX_HTTPS_PORT=443`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, matching `DATABASE_URL`, and matching `POSTGRES_EXPORTER_DATA_SOURCE_NAME`
- `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DB`, and matching `CLICKHOUSE_URL`
- distinct `SNOWFLAKE_WORKER_ID` values per API replica if split later
- strong Grafana admin password
- production Redis and Redpanda credentials if not using local compose defaults

## 3. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
make migrate
make seed
make clickhouse-migrate
make redpanda-topics
```

This starts an HTTP-only production stack that serves on `:80` and keeps Grafana, Prometheus, Loki, and Tempo internal to Docker. Keep `ufw` enabled so only OpenSSH and Nginx are reachable.

## 4. TLS

For a domain-backed deployment, issue a certificate first, then set:

```dotenv
NGINX_CONF=prod.tls.conf
NGINX_CERTS_DIR=/etc/letsencrypt/live/yourdomain.example
CORS_ORIGINS=https://yourdomain.example
```

Start with the TLS override so Compose publishes `443` and mounts the cert directory:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.tls.yml up -d --build
```

The cert directory must contain `fullchain.pem` and `privkey.pem`.

## 5. Health Checks

```bash
curl -f http://localhost/api/v1/health
curl -f http://localhost/api/v1/ready
```

Smoke test:

- Open `/api/docs` and `/api/redoc`.
- Log in as `host@livequiz.local` / `host`.
- Create or use a seeded quiz, open a room, join as a player, and finish a short match.
