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

REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
WS_URL=${WS_URL:-ws://localhost:8080/ws}
INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
FIREHOSE_STREAM=${FIREHOSE_STREAM:-stream:chat.firehose}
ROOM_ID=${ROOM_ID:-room:demo}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
TEST_ID="${timestamp}_$$"
MARKER="E2E_TEST_${TEST_ID}"

PAYLOAD=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"${TEST_ID}","ts":"${timestamp}","room_id":"${ROOM_ID}","origin":"human","user_id":"user_e2e","display_name":"viewer_e2e","content":"${MARKER} message","mentions":[],"emotes":[],"badges":[],"style":null,"client_meta":null,"moderation":null,"trace":{"producer":"stub_publisher"}}
EJSON
)

echo "Publishing test message with marker ${MARKER} to ${INGEST_STREAM}..."
docker exec "${REDIS_CONTAINER}" redis-cli XADD "${INGEST_STREAM}" * data "${PAYLOAD}" >/dev/null

echo "Waiting for WebSocket delivery from ${WS_URL}..."
if timeout 10 npx --yes wscat@8 -c "${WS_URL}" -x "{\"type\":\"subscribe\",\"room_id\":\"${ROOM_ID}\"}" 2>/tmp/wscat.err | grep -m1 "${MARKER}"; then
  echo "PASS: Received message with marker over WebSocket."
else
  echo "FAIL: Did not receive message over WebSocket within timeout." >&2
  if [ -s /tmp/wscat.err ]; then
    echo "wscat output:" >&2
    cat /tmp/wscat.err >&2
  fi
  exit 1
fi

sleep 1

echo "Checking firehose for marker and trace metadata..."
FIREHOSE_OUTPUT=$(docker exec "${REDIS_CONTAINER}" redis-cli XREVRANGE "${FIREHOSE_STREAM}" + - COUNT 50)
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "${MARKER}"; then
  echo "FAIL: Marker not found in firehose range." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q '"producer":"stub_publisher"'; then
  echo "FAIL: firehose entry missing original producer." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q 'processed_by'; then
  echo "FAIL: firehose entry missing processed_by trace." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q 'chat_gateway'; then
  echo "FAIL: firehose entry missing chat_gateway in processed_by." >&2
  exit 1
fi

echo "PASS: Firehose entry contains marker, original producer, and chat_gateway processing stamp."
