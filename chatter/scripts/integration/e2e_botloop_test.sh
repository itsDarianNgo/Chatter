#!/usr/bin/env bash
set -euo pipefail

# ---- tool checks ----
command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v npx >/dev/null 2>&1 || { echo "npx is required (for wscat)" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }

# ---- defaults (override via env) ----
REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
WS_URL=${WS_URL:-ws://localhost:8080/ws}
PERSONA_HTTP=${PERSONA_HTTP:-http://localhost:8090}

INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
FIREHOSE_STREAM=${FIREHOSE_STREAM:-stream:chat.firehose}
ROOM_ID=${ROOM_ID:-room:demo}

CONNECT_TIMEOUT_S=${CONNECT_TIMEOUT_S:-8}
BOT_REPLY_TIMEOUT_S=${BOT_REPLY_TIMEOUT_S:-15}
FIREHOSE_SCAN_COUNT=${FIREHOSE_SCAN_COUNT:-100000}
WS_HOLD_S=$((CONNECT_TIMEOUT_S + BOT_REPLY_TIMEOUT_S + 12))

# ---- ids/timestamps ----
TS_RFC3339=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ID_TS=$(date -u +%Y%m%dT%H%M%SZ)
TEST_ID="${ID_TS}_$$"
MARKER="E2E_TEST_BOTLOOP_${TEST_ID}"

# ---- quick health checks ----
if ! curl -sf "${PERSONA_HTTP}/healthz" >/dev/null; then
  echo "FAIL: persona_workers not reachable at ${PERSONA_HTTP}/healthz" >&2
  echo "Start it first (example):" >&2
  echo "  export REDIS_URL=redis://localhost:6379/0" >&2
  echo "  python -m apps.persona_workers.src.main" >&2
  exit 1
fi

if ! curl -sf "http://localhost:8080/healthz" >/dev/null; then
  echo "FAIL: chat_gateway not reachable at http://localhost:8080/healthz" >&2
  exit 1
fi

# ---- prefer local wscat if installed ----
if [ -x "./node_modules/.bin/wscat" ]; then
  WS_CMD=(./node_modules/.bin/wscat)
else
  WS_CMD=(npx --yes wscat@latest)
fi

TMP_WS_LOG="$(mktemp -t chatter_botloop_wscat.XXXXXX.log)"

cleanup() {
  if [ -n "${WS_PID:-}" ] && kill -0 "${WS_PID:-0}" >/dev/null 2>&1; then
    kill "${WS_PID}" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "${WS_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "$TMP_WS_LOG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ---- capture firehose tail id BEFORE test publish ----
FIREHOSE_TAIL_ID="$(
  docker exec "${REDIS_CONTAINER}" redis-cli XREVRANGE "${FIREHOSE_STREAM}" + - COUNT 1 \
    | grep -Eo '[0-9]{10,}-[0-9]+' | head -n1 || true
)"
if [ -z "${FIREHOSE_TAIL_ID}" ]; then
  FIREHOSE_TAIL_ID="0-0"
fi

echo "Connecting WS (${WS_URL}) and subscribing to ${ROOM_ID}..."
(
  echo "{\"type\":\"subscribe\",\"room_id\":\"${ROOM_ID}\"}"
  sleep "${WS_HOLD_S}"
) | "${WS_CMD[@]}" -c "${WS_URL}" >"$TMP_WS_LOG" 2>&1 &
WS_PID=$!

# Wait for subscribe ACK (wscat doesn't always print "Connected" banner in non-TTY mode)
start=$SECONDS
while (( SECONDS - start < CONNECT_TIMEOUT_S )); do
  if grep -q "subscribed" "$TMP_WS_LOG"; then
    break
  fi
  if grep -qiE "error|failed|ECONN|closed|handshake" "$TMP_WS_LOG"; then
    echo "FAIL: WebSocket error. wscat log:" >&2
    cat "$TMP_WS_LOG" >&2
    exit 1
  fi
  sleep 0.2
done

if ! grep -q "subscribed" "$TMP_WS_LOG"; then
  echo "FAIL: WebSocket did not subscribe within ${CONNECT_TIMEOUT_S}s. wscat log:" >&2
  cat "$TMP_WS_LOG" >&2
  exit 1
fi

# ---- publish a HUMAN trigger to ingest (gateway will forward to firehose) ----
HUMAN_PAYLOAD=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"human_${TEST_ID}","ts":"${TS_RFC3339}","room_id":"${ROOM_ID}","origin":"human","user_id":"user_e2e","display_name":"viewer_e2e","content":"${MARKER} hello","reply_to":null,"mentions":[],"emotes":[],"badges":[],"trace":{"producer":"e2e_botloop"}}
EJSON
)

echo "Publishing human trigger (${MARKER}) to ${INGEST_STREAM}..."
printf '%s' "$HUMAN_PAYLOAD" | docker exec -i "${REDIS_CONTAINER}" redis-cli -x XADD "${INGEST_STREAM}" "*" data >/dev/null

# ---- wait for a BOT reply over WS from persona_workers ----
# We look for:
# - marker token (generator should echo marker)
# - origin bot
# - producer persona_worker
echo "Waiting for bot reply over WS (timeout ${BOT_REPLY_TIMEOUT_S}s)..."
start=$SECONDS
while (( SECONDS - start < BOT_REPLY_TIMEOUT_S )); do
  if grep -q "${MARKER}" "$TMP_WS_LOG" \
     && (grep -q '"origin": "bot"' "$TMP_WS_LOG" || grep -q '"origin":"bot"' "$TMP_WS_LOG") \
     && (grep -q 'persona_worker' "$TMP_WS_LOG"); then
    echo "PASS: Saw bot reply over WS containing marker and persona_worker trace."
    break
  fi
  sleep 0.2
done

if ! (grep -q "${MARKER}" "$TMP_WS_LOG" && grep -q 'persona_worker' "$TMP_WS_LOG"); then
  echo "FAIL: Did not observe persona_worker bot reply over WS within timeout." >&2
  echo "---- wscat log ----" >&2
  cat "$TMP_WS_LOG" >&2
  echo "---- persona_workers stats ----" >&2
  curl -s "${PERSONA_HTTP}/stats" >&2 || true
  echo "" >&2
  echo "---- chat_gateway stats ----" >&2
  curl -s "http://localhost:8080/stats" >&2 || true
  echo "" >&2
  exit 1
fi

# ---- verify firehose contains bot reply AFTER tail ----
echo "Checking firehose for bot reply (marker + persona_worker + processed_by chat_gateway)..."
FIREHOSE_OUTPUT="$(
  docker exec "${REDIS_CONTAINER}" redis-cli XRANGE "${FIREHOSE_STREAM}" "(${FIREHOSE_TAIL_ID}" + COUNT "${FIREHOSE_SCAN_COUNT}"
)"

if ! echo "${FIREHOSE_OUTPUT}" | grep -q "${MARKER}"; then
  echo "FAIL: Marker not found in firehose entries after ${FIREHOSE_TAIL_ID}." >&2
  exit 1
fi

# Token-based checks (redis-cli output may escape JSON)
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "persona_worker"; then
  echo "FAIL: firehose output does not include persona_worker token." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "processed_by"; then
  echo "FAIL: firehose entry missing processed_by." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "chat_gateway"; then
  echo "FAIL: firehose entry missing chat_gateway in processed_by." >&2
  exit 1
fi
if ! echo "${FIREHOSE_OUTPUT}" | grep -q "origin" || ! echo "${FIREHOSE_OUTPUT}" | grep -q "bot"; then
  echo "FAIL: firehose output does not appear to contain a bot origin entry for marker." >&2
  exit 1
fi

echo "PASS: Bot loop verified (firehose → persona_workers → ingest → gateway → WS → firehose)."
