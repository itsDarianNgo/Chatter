#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT" || exit 1

print_help() {
  echo "Usage: bash scripts/dev/run_stream_demo.sh"
  echo
  echo "Starts the local compose stack, frame/transcript publishers, and observation tailer."
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  print_help
  exit 0
fi

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "FAIL: missing dependency '$name' on PATH."
    return 1
  fi
  return 0
}

if ! require_cmd docker; then
  echo "HINT: install Docker Desktop and ensure 'docker' is available."
  exit 2
fi

PYTHON_BIN="python"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "FAIL: missing dependency 'python' on PATH."
    exit 2
  fi
fi

if ! require_cmd node; then
  echo "HINT: install Node.js to run the observation tailer."
  exit 2
fi

redis_url="${REDIS_URL_HOST:-${REDIS_URL:-redis://127.0.0.1:6379/0}}"
export REDIS_URL_HOST="$redis_url"

echo "Using Redis URL: $redis_url"
echo "Starting compose stack..."
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build
if [[ $? -ne 0 ]]; then
  echo "FAIL: docker compose up failed."
  exit 2
fi

echo "Waiting for services..."
bash scripts/integration/wait_for_services.sh
if [[ $? -ne 0 ]]; then
  echo "FAIL: services did not become healthy."
  exit 2
fi

fixture_path="fixtures/stream/frame_fixture_1.png"
frame_args=("--mode" "screen")
if ! "$PYTHON_BIN" -c "import mss" >/dev/null 2>&1; then
  if [[ -f "$fixture_path" ]]; then
    echo "mss not available; using fixture file mode."
    frame_args=("--mode" "file" "--file" "$fixture_path")
  else
    echo "FAIL: missing mss and fixture image (${fixture_path})."
    echo "HINT: install mss (pip install mss) or add the fixture file."
    exit 2
  fi
fi

pids=()
cleanup_ran=0
cleanup() {
  if [[ "$cleanup_ran" -eq 1 ]]; then
    return
  fi
  cleanup_ran=1
  echo "Stopping demo..."
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1
    fi
  done
  for pid in "${pids[@]}"; do
    wait "$pid" >/dev/null 2>&1
  done
}

trap cleanup INT TERM EXIT

echo "Starting frame publisher..."
"$PYTHON_BIN" scripts/capture/publish_frames.py \
  --room-id room:demo \
  --interval-ms 1500 \
  "${frame_args[@]}" \
  --redis-url "$redis_url" &
pids+=("$!")

echo "Starting observation tailer..."
node scripts/dev/tail_observations.mjs \
  --room-id room:demo \
  --redis-url "$redis_url" \
  --since now &
pids+=("$!")

echo "Type transcript lines (Ctrl+C to stop):"
"$PYTHON_BIN" scripts/capture/publish_transcripts.py \
  --room-id room:demo \
  --mode stdin \
  --redis-url "$redis_url"
