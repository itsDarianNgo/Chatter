#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 2; }

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.test.yml -f docker-compose.memory-llm.test.yml"

cleanup() {
  $COMPOSE down -v || true
}
trap cleanup EXIT

echo "Bringing up compose stack (LLM memory)..."
$COMPOSE up -d --build

echo "Waiting for gateway and persona_workers health..."
bash scripts/integration/wait_for_services.sh

echo "Running LLM memory extraction E2E test..."
npm run test:e2e:memory:llm
