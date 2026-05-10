#!/usr/bin/env bash
# Dump the LiveQuiz Postgres database to ./backups/livequiz-YYYYMMDD-HHMMSS.sql.gz

set -euo pipefail

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"

ts="$(date -u +%Y%m%d-%H%M%S)"
out="$OUT_DIR/livequiz-${ts}.sql.gz"

docker compose exec -T postgres pg_dump -U livequiz -d livequiz | gzip > "$out"
echo "wrote $out"
