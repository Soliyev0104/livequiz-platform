#!/usr/bin/env bash
# Create the LiveQuiz Redpanda topics.
#
# Idempotent — `rpk topic create` returns a non-zero exit code when the
# topic already exists; we filter that out so re-running the script in
# CI or via `make redpanda-topics` is safe.
#
# Two run modes are supported:
#
#   * Host (default) — invoke via `make redpanda-topics`. The script
#     calls `docker compose exec redpanda rpk ...` to reach the broker
#     using the in-cluster network.
#
#   * In-container — set RPK_MODE=in-container to call `rpk` directly
#     (used by the `redpanda-init` sidecar in docker-compose.yml which
#     runs once after the broker is healthy on first boot).

set -euo pipefail

TOPICS=(
  "livequiz.events.room"
  "livequiz.events.match"
  "livequiz.events.answer"
  "livequiz.events.moderation"
  "livequiz.events.dead_letter"
)

PARTITIONS="${REDPANDA_PARTITIONS:-3}"
REPLICAS="${REDPANDA_REPLICAS:-1}"
MODE="${RPK_MODE:-host}"
BROKERS="${REDPANDA_BROKERS:-redpanda:9092}"

if [[ "$MODE" == "in-container" ]]; then
  RPK=(rpk --brokers "$BROKERS")
else
  RPK=(docker compose exec -T redpanda rpk)
fi

for t in "${TOPICS[@]}"; do
  if "${RPK[@]}" topic create "$t" --partitions "$PARTITIONS" --replicas "$REPLICAS" 2>&1 | tee /tmp/rpk.out; then
    :
  else
    # Non-fatal when the topic already exists.
    if grep -qiE "(already exists|TOPIC_ALREADY_EXISTS)" /tmp/rpk.out; then
      echo "topic '$t' already exists — ok"
    else
      echo "rpk topic create failed for '$t'" >&2
      exit 1
    fi
  fi
done

"${RPK[@]}" topic list
