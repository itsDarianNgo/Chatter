#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || {
  echo "docker is required for this test" >&2
  exit 2
}

command -v npx >/dev/null 2>&1 || {
  echo "npx is required (for wscat). Install Node/npm and re-run." >&2
  exit 2
}

command -v curl >/dev/null 2>&1 || {
  echo "curl is required for this test" >&2
  exit 2
}

REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
WS_URL=${WS_URL:-ws://localhost:8080/ws}
PERSONA_HTTP=${PERSONA_HTTP:-http://localhost:8090/healthz}
INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
FIREHOSE_STREAM=${FIREHOSE_STREAM:-stream:chat.firehose}
ROOM_ID=${ROOM_ID:-room:demo}

if ! curl -fsS "${PERSONA_HTTP}" >/dev/null; then
  echo "persona_workers health endpoint is not responding at ${PERSONA_HTTP}" >&2
  exit 1
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
TEST_ID="${timestamp}_$$"
MARKER="E2E_MARKER_${TEST_ID}"

PAYLOAD=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"${TEST_ID}","ts":"${timestamp}","room_id":"${ROOM_ID}","origin":"human","user_id":"user_e2e","display_name":"viewer_e2e","content":"${MARKER} message","mentions":[],"emotes":[],"badges":[],"style":null,"client_meta":null,"moderation":null,"trace":{"producer":"stub_publisher"}}
EJSON
)

echo "Publishing marker ${MARKER} to ${INGEST_STREAM}..."
docker exec "${REDIS_CONTAINER}" redis-cli XADD "${INGEST_STREAM}" * data "${PAYLOAD}" >/dev/null

WS_LOG=$(mktemp)
echo "Waiting for bot reply over WebSocket (${WS_URL})..."
set +e
timeout 20 npx --yes wscat@8 -c "${WS_URL}" -x "{\"type\":\"subscribe\",\"room_id\":\"${ROOM_ID}\"}" >"${WS_LOG}" 2>/tmp/wscat_botloop.err
WS_EXIT=$?
set -e

if [ ${WS_EXIT} -ne 0 ] && [ ${WS_EXIT} -ne 124 ]; then
  echo "wscat failed with exit code ${WS_EXIT}" >&2
  if [ -s /tmp/wscat_botloop.err ]; then
    echo "wscat stderr:" >&2
    cat /tmp/wscat_botloop.err >&2
  fi
  exit 1
fi

if ! grep -q "${MARKER}" "${WS_LOG}"; then
  echo "FAIL: Did not observe the marker on WebSocket." >&2
  exit 1
fi

if ! grep -q '"origin":"bot"' "${WS_LOG}"; then
  echo "FAIL: Did not observe a bot-origin message on WebSocket." >&2
  cat "${WS_LOG}" >&2
  exit 1
fi

if ! grep -q 'got it: E2E_MARKER_' "${WS_LOG}"; then
  echo "FAIL: Bot reply did not contain expected marker acknowledgement." >&2
  cat "${WS_LOG}" >&2
  exit 1
fi

echo "PASS: Observed bot reply over WebSocket. Checking firehose..."
FIREHOSE_OUTPUT=$(docker exec "${REDIS_CONTAINER}" redis-cli XREVRANGE "${FIREHOSE_STREAM}" + - COUNT 200)
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "${MARKER}"; then
  echo "FAIL: Marker not found in firehose entries." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q '"origin":"bot"'; then
  echo "FAIL: Bot-origin message not found in firehose." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q '"producer":"persona_worker"'; then
  echo "FAIL: Firehose entry missing persona_worker producer." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q 'got it: E2E_MARKER_'; then
  echo "FAIL: Firehose entry missing bot acknowledgement content." >&2
  exit 1
fi

echo "PASS: Botloop E2E test succeeded."
