# Deployment Guide

Target: one Ubuntu DigitalOcean droplet running Docker Compose behind Nginx.

## 1. Provision

Create an Ubuntu droplet, SSH in, then install Docker and firewall basics:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git ufw
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
- strong `JWT_SECRET` and `JWT_REFRESH_SECRET`
- public `CORS_ORIGINS`
- distinct `SNOWFLAKE_WORKER_ID` values per API replica if split later
- strong Grafana admin password
- production database, Redis, Redpanda, ClickHouse credentials if not using local compose defaults

## 3. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
make migrate
make seed
make clickhouse-migrate
make redpanda-topics
```

## 4. TLS

`ops/nginx/prod.conf` has commented certificate paths:

```nginx
# ssl_certificate     /etc/nginx/certs/fullchain.pem;
# ssl_certificate_key /etc/nginx/certs/privkey.pem;
```

Mount certificates into `/etc/nginx/certs/` with Certbot, a Certbot sidecar, or another ACME workflow, then uncomment those lines and reload the Nginx container.

## 5. Health Checks

```bash
curl -f http://localhost/api/v1/health
curl -f http://localhost/api/v1/ready
```

Smoke test:

- Open `/api/docs` and `/api/redoc`.
- Log in as `host@livequiz.local` / `host`.
- Create or use a seeded quiz, open a room, join as a player, and finish a short match.
