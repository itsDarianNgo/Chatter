#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v npx >/dev/null 2>&1 || { echo "npx is required (for wscat)" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }
command -v python >/dev/null 2>&1 || { echo "python is required" >&2; exit 2; }

REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
WS_URL=${WS_URL:-ws://localhost:8080/ws}
PERSONA_HTTP=${PERSONA_HTTP:-http://localhost:8090}
INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
FIREHOSE_STREAM=${FIREHOSE_STREAM:-stream:chat.firehose}
ROOM_ID=${ROOM_ID:-room:demo}
CONNECT_TIMEOUT_S=${CONNECT_TIMEOUT_S:-8}
WAIT_AFTER_PUBLISH_S=${WAIT_AFTER_PUBLISH_S:-2}

TS_RFC3339=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ID_TS=$(date -u +%Y%m%dT%H%M%SZ)
TEST_ID="${ID_TS}_$$"
MARKER="E2E_TEST_POLICY_${TEST_ID}"

fail_with_stats() {
  local message="$1" stats="$2"
  echo "FAIL: ${message}" >&2
  echo "---- /stats ----" >&2
  echo "${stats}" >&2
  exit 1
}

fetch_stats() {
  curl -s "${PERSONA_HTTP}/stats"
}

get_counter() {
  local stats="$1" key="$2"
  printf '%s' "${stats}" | python - "$key" <<'PY'
import json, sys
key = sys.argv[1]
try:
    data = json.loads(sys.stdin.read())
except Exception:
    print("")
    sys.exit(0)
val = data
for part in key.split('.'):
    if isinstance(val, dict) and part in val:
        val = val[part]
    else:
        val = None
        break
if isinstance(val, (int, float)):
    print(int(val))
else:
    print("")
PY
}

require_counter() {
  local stats="$1" key="$2" label="$3"
  local value
  value=$(get_counter "${stats}" "${key}")
  if [ -z "${value}" ]; then
    fail_with_stats "Missing counter for ${label} (${key})" "${stats}"
  fi
  echo "${value}"
}

get_reason_counter() {
  local stats="$1" reason="$2" fallback="$3"
  local val
  val=$(get_counter "${stats}" "decisions_by_reason.${reason}")
  if [ -z "${val}" ] && [ -n "${fallback}" ]; then
    val=$(get_counter "${stats}" "${fallback}")
  fi
  echo "${val}"
}

assert_increase() {
  local before="$1" after="$2" label="$3"
  if [ -z "${before}" ] || [ -z "${after}" ]; then
    echo "FAIL: assert_increase received empty values for ${label}" >&2
    exit 1
  fi
  if [ "${after}" -lt $((before + 1)) ]; then
    echo "FAIL: ${label} did not increase (before=${before}, after=${after})" >&2
    exit 1
  fi
}

choose_persona_display_name() {
  local stats="$1"
  STATS_JSON="${stats}" python - <<'PY'
import json, os, pathlib
stats = json.loads(os.environ.get("STATS_JSON", "{}"))
enabled = stats.get("enabled_personas") or []
persona_id = enabled[0] if enabled else None
if persona_id:
    path = pathlib.Path("configs/personas") / f"{persona_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            display = data.get("presentation", {}).get("display_name") or data.get("persona_id") or persona_id
        except Exception:
            display = persona_id
    else:
        display = persona_id
else:
    display = "persona"
print(display)
PY
}

publish_message() {
  local msg_id="$1" origin="$2" content="$3" user_id="$4" display_name="$5"
  local payload
  payload=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"${msg_id}","ts":"${TS_RFC3339}","room_id":"${ROOM_ID}","origin":"${origin}","user_id":"${user_id}","display_name":"${display_name}","content":"${content}","reply_to":null,"mentions":[],"emotes":[],"badges":[],"trace":{"producer":"e2e_policy_probe"}}
EJSON
)
  printf '%s' "${payload}" | docker exec -i "${REDIS_CONTAINER}" redis-cli -x XADD "${INGEST_STREAM}" "*" data >/dev/null
}

# ---- health check ----
if ! curl -sf "${PERSONA_HTTP}/healthz" >/dev/null; then
  echo "FAIL: persona_workers not reachable at ${PERSONA_HTTP}/healthz" >&2
  exit 1
fi

BASE_STATS=$(fetch_stats)
BASE_PUBLISHED=$(require_counter "${BASE_STATS}" "messages_published" "messages_published")
BASE_REASON_BOT=$(get_reason_counter "${BASE_STATS}" "bot_origin" "messages_suppressed_bot_origin")
if [ -z "${BASE_REASON_BOT}" ]; then
  fail_with_stats "Missing bot_origin suppression counter" "${BASE_STATS}"
fi
BASE_REASON_COOLDOWN=$(get_reason_counter "${BASE_STATS}" "cooldown" "messages_suppressed_cooldown")
if [ -z "${BASE_REASON_COOLDOWN}" ]; then
  fail_with_stats "Missing cooldown suppression counter" "${BASE_STATS}"
fi
BASE_REASON_E2E=$(get_reason_counter "${BASE_STATS}" "e2e_forced" "")
if [ -z "${BASE_REASON_E2E}" ]; then
  BASE_REASON_E2E=0
fi

PERSONA_NAME=$(choose_persona_display_name "${BASE_STATS}")

if [ -x "./node_modules/.bin/wscat" ]; then
  WS_CMD=(./node_modules/.bin/wscat)
else
  WS_CMD=(npx --yes wscat@latest)
fi

TMP_WS_LOG="$(mktemp -t chatter_policy_probe_ws.XXXXXX.log)"
cleanup() {
  if [ -n "${WS_PID:-}" ] && kill -0 "${WS_PID:-0}" >/dev/null 2>&1; then
    kill "${WS_PID}" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "${WS_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "${TMP_WS_LOG}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Connecting WS (${WS_URL}) to ${ROOM_ID} (best-effort)..."
(
  echo "{\"type\":\"subscribe\",\"room_id\":\"${ROOM_ID}\"}"
  sleep "${WAIT_AFTER_PUBLISH_S}"
) | "${WS_CMD[@]}" -c "${WS_URL}" >"${TMP_WS_LOG}" 2>&1 &
WS_PID=$!

start=$SECONDS
while (( SECONDS - start < CONNECT_TIMEOUT_S )); do
  if grep -q "subscribed" "${TMP_WS_LOG}"; then
    break
  fi
  if grep -qiE "error|failed|ECONN|closed|handshake" "${TMP_WS_LOG}"; then
    echo "WS connection encountered an error (continuing test). Log:" >&2
    cat "${TMP_WS_LOG}" >&2
    break
  fi
  sleep 0.2
done

# Order: bot-origin suppression, forced marker (to ensure recent publish), cooldown pair, mention/hype, final forced marker
publish_message "policy_bot_origin_${TEST_ID}" "bot" "${MARKER} BOT_ORIGIN" "user_bot" "bot_account"
publish_message "policy_e2e_prime_${TEST_ID}" "human" "${MARKER} E2E_TEST_POLICY_TRIGGER" "user_prime" "prime_viewer"
publish_message "policy_cd_1_${TEST_ID}" "human" "${MARKER} COOLDOWN" "user_cd" "cooldown_viewer"
publish_message "policy_cd_2_${TEST_ID}" "human" "${MARKER} COOLDOWN" "user_cd2" "cooldown_viewer2"
publish_message "policy_mention_${TEST_ID}" "human" "@${PERSONA_NAME} POGGERS KEKW ${MARKER} MENTION_HYPE" "user_mh" "mentioner"
publish_message "policy_e2e_${TEST_ID}" "human" "${MARKER} E2E_TEST_POLICY_TRIGGER" "user_e2e" "forced_viewer"

sleep "${WAIT_AFTER_PUBLISH_S}"

AFTER_STATS=$(fetch_stats)
AFTER_PUBLISHED=$(require_counter "${AFTER_STATS}" "messages_published" "messages_published")
AFTER_REASON_BOT=$(get_reason_counter "${AFTER_STATS}" "bot_origin" "messages_suppressed_bot_origin")
AFTER_REASON_COOLDOWN=$(get_reason_counter "${AFTER_STATS}" "cooldown" "messages_suppressed_cooldown")
AFTER_REASON_E2E=$(get_reason_counter "${AFTER_STATS}" "e2e_forced" "")
if [ -z "${AFTER_REASON_E2E}" ]; then
  AFTER_REASON_E2E=0
fi

assert_increase "${BASE_REASON_BOT}" "${AFTER_REASON_BOT}" "bot-origin suppression"
assert_increase "${BASE_REASON_COOLDOWN}" "${AFTER_REASON_COOLDOWN}" "cooldown suppression"
assert_increase "${BASE_PUBLISHED}" "${AFTER_PUBLISHED}" "messages_published"

if [ "${AFTER_REASON_E2E}" -lt $((BASE_REASON_E2E + 1)) ]; then
  if ! echo "${AFTER_STATS}" | grep -q "e2e_forced"; then
    fail_with_stats "e2e_forced reason not observed" "${AFTER_STATS}"
  fi
fi

TAG_HITS=0
if echo "${AFTER_STATS}" | grep -q "p_used" || echo "${AFTER_STATS}" | grep -q "\"p\""; then
  TAG_HITS=$((TAG_HITS + 1))
fi
if echo "${AFTER_STATS}" | grep -q "h_value" || echo "${AFTER_STATS}" | grep -q "\"h\""; then
  TAG_HITS=$((TAG_HITS + 1))
fi
if echo "${AFTER_STATS}" | grep -q "rate_10s" || echo "${AFTER_STATS}" | grep -q "rate"; then
  TAG_HITS=$((TAG_HITS + 1))
fi
if echo "${AFTER_STATS}" | grep -qi "mention"; then
  TAG_HITS=$((TAG_HITS + 1))
fi
if echo "${AFTER_STATS}" | grep -qi "hype"; then
  TAG_HITS=$((TAG_HITS + 1))
fi

if [ "${TAG_HITS}" -lt 3 ]; then
  fail_with_stats "Decision tags missing required markers (hits=${TAG_HITS})" "${AFTER_STATS}"
fi

echo "PASS: policy probe succeeded"
echo "bot_origin delta: $((AFTER_REASON_BOT - BASE_REASON_BOT))"
echo "cooldown delta: $((AFTER_REASON_COOLDOWN - BASE_REASON_COOLDOWN))"
echo "messages_published delta: $((AFTER_PUBLISHED - BASE_PUBLISHED))"
echo "e2e_forced delta: $((AFTER_REASON_E2E - BASE_REASON_E2E))"
