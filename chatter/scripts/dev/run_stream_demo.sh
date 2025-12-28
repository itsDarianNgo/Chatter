#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT" || exit 1

print_help() {
  echo "Usage: bash scripts/dev/run_stream_demo.sh [--llm]"
  echo
  echo "Starts the local compose stack, frame/transcript publishers, and observation tailer."
  echo "  --llm  Enable LiteLLM-backed persona/perceptor (requires .env.local or exported env vars)."
}

use_llm=0
for arg in "$@"; do
  case "$arg" in
    --help|-h)
      print_help
      exit 0
      ;;
    --llm)
      use_llm=1
      ;;
  esac
done

if [[ "${DEV_LLM:-}" == "1" ]]; then
  use_llm=1
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
if [[ "$use_llm" -eq 1 ]]; then
  if [[ -f ".env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source ".env.local"
    set +a
  fi
  if [[ -z "${LITELLM_BASE_URL:-}" && -z "${LLM_BASE_URL:-}" ]]; then
    echo "FAIL: missing LITELLM_BASE_URL (or LLM_BASE_URL) for --llm."
    exit 2
  fi
  if [[ -z "${LITELLM_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" && -z "${LLM_API_KEY:-}" ]]; then
    echo "FAIL: missing LITELLM_API_KEY (or OPENAI_API_KEY/LLM_API_KEY) for --llm."
    exit 2
  fi
  if [[ -z "${PERSONA_LLM_MODEL:-}" && -z "${LLM_MODEL:-}" ]]; then
    echo "FAIL: missing PERSONA_LLM_MODEL (or LLM_MODEL) for --llm."
    exit 2
  fi
  if [[ -z "${PERCEPTOR_VISION_MODEL:-}" && -z "${PERCEPTOR_LLM_MODEL:-}" ]]; then
    echo "WARN: PERCEPTOR_VISION_MODEL not set; stream_perceptor will reuse the persona model."
  fi
fi
echo "Starting compose stack..."
compose_files=(-f docker-compose.yml -f docker-compose.test.yml)
if [[ "$use_llm" -eq 1 ]]; then
  compose_files+=(-f docker-compose.local.yml)
fi
docker compose "${compose_files[@]}" up -d --build
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
