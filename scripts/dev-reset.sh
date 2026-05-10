#!/usr/bin/env bash
# Wipe local volumes, rebuild, migrate, seed.
# Use when something is irrevocably broken in your dev env.

set -euo pipefail

docker compose down -v
docker compose up -d --build
make migrate
make seed
