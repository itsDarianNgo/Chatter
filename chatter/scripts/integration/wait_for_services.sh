#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_S=${TIMEOUT_S:-45}
SLEEP_S=${SLEEP_S:-0.5}
GATEWAY_URL=${GATEWAY_URL:-http://localhost:8080/healthz}
PERSONA_URL=${PERSONA_URL:-http://localhost:8090/healthz}

start=$(date +%s)

wait_for() {
  local url="$1" name="$2"
  while true; do
    if curl -sf "$url" >/dev/null; then
      echo "$name healthy"
      return 0
    fi
    now=$(date +%s)
    if (( now - start >= TIMEOUT_S )); then
      echo "FAIL: $name did not become healthy within ${TIMEOUT_S}s" >&2
      exit 1
    fi
    sleep "$SLEEP_S"
  done
}

wait_for "$GATEWAY_URL" "gateway"
wait_for "$PERSONA_URL" "persona_workers"
