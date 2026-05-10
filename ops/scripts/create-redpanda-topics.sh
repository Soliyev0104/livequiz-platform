#!/usr/bin/env bash
# Create the LiveQuiz Redpanda topics. Idempotent: existing topics produce a warning, not a failure.

set -euo pipefail

TOPICS=(
  "livequiz.events.room"
  "livequiz.events.match"
  "livequiz.events.answer"
  "livequiz.events.moderation"
  "livequiz.events.dead_letter"
)

for t in "${TOPICS[@]}"; do
  docker compose exec -T redpanda rpk topic create "$t" --partitions 3 --replicas 1 || true
done

docker compose exec -T redpanda rpk topic list
