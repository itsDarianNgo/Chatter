#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 2; }

cleanup() {
  docker compose -f docker-compose.yml -f docker-compose.test.yml down -v || true
}
trap cleanup EXIT

echo "Bringing up compose stack..."
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build

echo "Waiting for gateway and persona_workers health..."
bash scripts/integration/wait_for_services.sh

echo "Running E2E tests..."
npm run test:e2e
npm run test:e2e:botloop
npm run test:e2e:policy
