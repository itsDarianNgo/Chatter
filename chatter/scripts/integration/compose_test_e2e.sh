#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 2; }

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.test.yml"

cleanup() {
  $COMPOSE down -v || true
}
trap cleanup EXIT

restart_persona_workers() {
  echo "Restarting persona_workers to reset in-memory state (budgets/cooldowns/dedupe)..."
  $COMPOSE restart persona_workers
  # Re-use existing health gate; it’s fine if it checks gateway too.
  bash scripts/integration/wait_for_services.sh
}

echo "Bringing up compose stack..."
$COMPOSE up -d --build

echo "Waiting for gateway and persona_workers health..."
bash scripts/integration/wait_for_services.sh

echo "Running E2E tests..."

# 1) Gateway/WS/firehose contract
npm run test:e2e

# Reset persona state so later tests aren't impacted by any forced-marker replies.
restart_persona_workers

# 2) Memory pipeline (requires generation to exercise read-before-generate)
npm run test:e2e:memory

# Reset persona state so budgets from memory test don't suppress botloop.
restart_persona_workers

# 3) Bot loop (firehose → persona → ingest → gateway → WS → firehose)
npm run test:e2e:botloop

# Reset again so policy probe deltas start from a clean baseline.
restart_persona_workers

# 4) Policy probe (cooldown/budget/bot_origin tagging)
npm run test:e2e:policy

# 5) Stream perception (frames + transcripts -> observations)
npm run test:e2e:stream

# Reset persona state so observation buffer is clean for reactivity.
restart_persona_workers

# 6) Reactivity (observations -> persona replies)
npm run test:e2e:reactivity
