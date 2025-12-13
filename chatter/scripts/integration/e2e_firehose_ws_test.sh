#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo "docker is required for this test" >&2; exit 2; }
command -v npx >/dev/null 2>&1 || { echo "npx is required (for wscat). Install Node/npm and re-run." >&2; exit 2; }

REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
WS_URL=${WS_URL:-ws://localhost:8080/ws}
INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
FIREHOSE_STREAM=${FIREHOSE_STREAM:-stream:chat.firehose}
ROOM_ID=${ROOM_ID:-room:demo}

CONNECT_TIMEOUT_S=${CONNECT_TIMEOUT_S:-8}
RECEIVE_TIMEOUT_S=${RECEIVE_TIMEOUT_S:-12}
FIREHOSE_SCAN_COUNT=${FIREHOSE_SCAN_COUNT:-50000}
WS_HOLD_S=$((CONNECT_TIMEOUT_S + RECEIVE_TIMEOUT_S + 10))

# RFC3339 timestamp for schema format: date-time
TS_RFC3339=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ID_TS=$(date -u +%Y%m%dT%H%M%SZ)
TEST_ID="${ID_TS}_$$"
MARKER="E2E_TEST_${TEST_ID}"

PAYLOAD=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"${TEST_ID}","ts":"${TS_RFC3339}","room_id":"${ROOM_ID}","origin":"human","user_id":"user_e2e","display_name":"viewer_e2e","content":"${MARKER} message","reply_to":null,"mentions":[],"emotes":[],"badges":[],"trace":{"producer":"stub_publisher"}}
EJSON
)

# Prefer local wscat if installed; else use latest via npx
if [ -x "./node_modules/.bin/wscat" ]; then
  WS_CMD=(./node_modules/.bin/wscat)
else
  WS_CMD=(npx --yes wscat@latest)
fi

TMP_WS_LOG="$(mktemp -t chatter_wscat.XXXXXX.log)"

cleanup() {
  if [ -n "${WS_PID:-}" ] && kill -0 "${WS_PID:-0}" >/dev/null 2>&1; then
    kill "${WS_PID}" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "${WS_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "$TMP_WS_LOG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Capture firehose tail BEFORE the test publishes anything (prevents “last N entries” race)
FIREHOSE_TAIL_ID="$(
  docker exec "${REDIS_CONTAINER}" redis-cli XREVRANGE "${FIREHOSE_STREAM}" + - COUNT 1 \
    | grep -Eo '[0-9]{10,}-[0-9]+' | head -n1 || true
)"
if [ -z "${FIREHOSE_TAIL_ID}" ]; then
  FIREHOSE_TAIL_ID="0-0"
fi

echo "Connecting to WebSocket at ${WS_URL} and subscribing to ${ROOM_ID}..."

# Keep stdin open so wscat doesn't exit; send subscribe immediately
(
  echo "{\"type\":\"subscribe\",\"room_id\":\"${ROOM_ID}\"}"
  sleep "${WS_HOLD_S}"
) | "${WS_CMD[@]}" -c "${WS_URL}" >"$TMP_WS_LOG" 2>&1 &
WS_PID=$!

# Wait until we see either:
# - typical banner "Connected"
# - OR subscribe ACK {"type":"subscribed"...}
start=$SECONDS
while (( SECONDS - start < CONNECT_TIMEOUT_S )); do
  if grep -qi "Connected" "$TMP_WS_LOG"; then
    break
  fi
  if grep -q "\"type\": \"subscribed\"" "$TMP_WS_LOG" || grep -q "\"type\":\"subscribed\"" "$TMP_WS_LOG"; then
    break
  fi
  if grep -qiE "error|failed|ECONN|closed|handshake" "$TMP_WS_LOG"; then
    echo "FAIL: WebSocket connection error. wscat log:" >&2
    cat "$TMP_WS_LOG" >&2
    exit 1
  fi
  sleep 0.2
done

if ! (grep -qi "Connected" "$TMP_WS_LOG" || grep -q "subscribed" "$TMP_WS_LOG"); then
  echo "FAIL: WebSocket did not connect/subscribe within ${CONNECT_TIMEOUT_S}s. wscat log:" >&2
  cat "$TMP_WS_LOG" >&2
  exit 1
fi

# Ensure subscribe ack likely processed to reduce flakiness
start=$SECONDS
while (( SECONDS - start < 3 )); do
  if grep -q "subscribed" "$TMP_WS_LOG"; then
    break
  fi
  sleep 0.2
done

echo "Publishing test message with marker ${MARKER} to ${INGEST_STREAM}..."
# Publish safely: redis-cli reads field value from stdin (-x)
printf '%s' "$PAYLOAD" | docker exec -i "${REDIS_CONTAINER}" redis-cli -x XADD "${INGEST_STREAM}" "*" data >/dev/null

echo "Waiting for WebSocket delivery (timeout ${RECEIVE_TIMEOUT_S}s)..."
start=$SECONDS
while (( SECONDS - start < RECEIVE_TIMEOUT_S )); do
  if grep -q "${MARKER}" "$TMP_WS_LOG"; then
    echo "PASS: Received message with marker over WebSocket."
    break
  fi
  sleep 0.2
done

if ! grep -q "${MARKER}" "$TMP_WS_LOG"; then
  echo "FAIL: Did not receive message over WebSocket within timeout." >&2
  echo "wscat log:" >&2
  cat "$TMP_WS_LOG" >&2
  exit 1
fi

sleep 0.8

echo "Checking firehose for marker and trace metadata..."
FIREHOSE_OUTPUT="$(
  docker exec "${REDIS_CONTAINER}" redis-cli XRANGE "${FIREHOSE_STREAM}" "(${FIREHOSE_TAIL_ID}" + COUNT "${FIREHOSE_SCAN_COUNT}"
)"

if ! echo "${FIREHOSE_OUTPUT}" | grep -q "${MARKER}"; then
  echo "FAIL: Marker not found in firehose entries after ${FIREHOSE_TAIL_ID} (COUNT=${FIREHOSE_SCAN_COUNT})." >&2
  exit 1
fi

# Allow for escaped JSON in redis-cli output: just ensure tokens exist
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "producer" || ! echo "${FIREHOSE_OUTPUT}" | grep -q "stub_publisher"; then
  echo "FAIL: firehose entry missing original producer (stub_publisher)." >&2
  exit 1
fi

if ! echo "${FIREHOSE_OUTPUT}" | grep -q "processed_by"; then
  echo "FAIL: firehose entry missing processed_by trace." >&2
  exit 1
fi

if ! echo "${FIREHOSE_OUTPUT}" | grep -q "chat_gateway"; then
  echo "FAIL: firehose entry missing chat_gateway in processed_by." >&2
  exit 1
fi

echo "PASS: Firehose entry contains marker, original producer, and chat_gateway processing stamp."
