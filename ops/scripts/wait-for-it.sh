#!/usr/bin/env bash
# wait-for-it.sh — minimal port-wait helper.
# Use as: wait-for-it.sh host:port [-t seconds] -- command args
# This is a stripped-down variant of vishnubob/wait-for-it suitable for our compose
# entrypoints. Replace with the upstream version if more options are needed.

set -euo pipefail

TIMEOUT=30
HOST=""
PORT=""

usage() {
  cat <<EOF
Usage: $0 host:port [-t timeout] [-- command args]
EOF
  exit 1
}

[ "$#" -lt 1 ] && usage

HOSTPORT="$1"; shift
HOST="${HOSTPORT%%:*}"
PORT="${HOSTPORT##*:}"

while [ $# -gt 0 ]; do
  case "$1" in
    -t) TIMEOUT="$2"; shift 2;;
    --) shift; break;;
    *) usage;;
  esac
done

start=$(date +%s)
while ! (exec 3<>"/dev/tcp/$HOST/$PORT") 2>/dev/null; do
  now=$(date +%s)
  if [ $((now - start)) -ge "$TIMEOUT" ]; then
    echo "wait-for-it: timeout waiting for $HOST:$PORT after ${TIMEOUT}s" >&2
    exit 1
  fi
  sleep 1
done

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
