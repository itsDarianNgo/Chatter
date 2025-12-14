#!/usr/bin/env bash
set -euo pipefail

REDIS_CONTAINER=${REDIS_CONTAINER:-chatter-redis-1}
PERSONA_HTTP=${PERSONA_HTTP:-http://localhost:8090}
INGEST_STREAM=${INGEST_STREAM:-stream:chat.ingest}
ROOM_ID=${ROOM_ID:-room:demo}
WAIT_AFTER_PUBLISH_S=${WAIT_AFTER_PUBLISH_S:-2}
CONNECT_TIMEOUT_S=${CONNECT_TIMEOUT_S:-10}

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }

fetch_stats() {
  curl -s "${PERSONA_HTTP}/stats" | {
    if command -v python >/dev/null 2>&1; then
      python -c 'import sys,json; print(json.dumps(json.load(sys.stdin), separators=(",", ":")))'
    else
      tr -d '\n'
    fi
  }
}

extract_int() {
  local stats="$1" key="$2"
  python - "$key" <<<"${stats}" <<'PY'
import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
key=sys.argv[1]
val=data.get(key)
if isinstance(val,(int,float)):
    print(int(val))
else:
    print("")
PY
}

extract_bool() {
  local stats="$1" key="$2"
  python - "$key" <<<"${stats}" <<'PY'
import json,sys
key=sys.argv[1]
try:
    data=json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
val=data.get(key)
if isinstance(val,bool):
    print("true" if val else "false")
elif isinstance(val,str) and val.lower() in ("true","false"):
    print(val.lower())
else:
    print("")
PY
}

extract_string() {
  local stats="$1" key="$2"
  python - "$key" <<<"${stats}" <<'PY'
import json,sys
key=sys.argv[1]
try:
    data=json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
val=data.get(key)
if isinstance(val,str):
    print(val)
else:
    print("")
PY
}

require_counter() {
  local stats="$1" key="$2" label="$3"
  local val
  val=$(extract_int "${stats}" "${key}")
  if [ -z "${val}" ]; then
    echo "FAIL: missing counter ${label} (${key})" >&2
    echo "---- /stats ----" >&2
    echo "${stats}" >&2
    exit 1
  fi
  echo "${val}"
}

publish_message() {
  local msg_id="$1" origin="$2" content="$3" user_id="$4" display_name="$5"
  local payload ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  payload=$(cat <<EJSON | tr -d '\n'
{"schema_name":"ChatMessage","schema_version":"1.0.0","id":"${msg_id}","ts":"${ts}","room_id":"${ROOM_ID}","origin":"${origin}","user_id":"${user_id}","display_name":"${display_name}","content":"${content}","reply_to":null,"mentions":[],"emotes":[],"badges":[],"trace":{"producer":"e2e_memory"}}
EJSON
)
  printf '%s' "${payload}" | docker exec -i "${REDIS_CONTAINER}" redis-cli -x XADD "${INGEST_STREAM}" "*" data >/dev/null
}

if ! curl -sf "${PERSONA_HTTP}/healthz" >/dev/null; then
  echo "FAIL: persona_workers not reachable at ${PERSONA_HTTP}/healthz" >&2
  exit 1
fi

BASE_STATS=$(fetch_stats)
MEMORY_ENABLED=$(extract_bool "${BASE_STATS}" "memory_enabled")
if [ "${MEMORY_ENABLED}" != "true" ]; then
  LAST_ERR=$(extract_string "${BASE_STATS}" "last_memory_error")
  echo "FAIL: memory is disabled; last_memory_error=${LAST_ERR}" >&2
  exit 1
fi
BASE_WRITES=$(require_counter "${BASE_STATS}" "memory_writes_accepted" "memory_writes_accepted")
BASE_READS=$(require_counter "${BASE_STATS}" "memory_reads_succeeded" "memory_reads_succeeded")
BASE_ITEMS=$(require_counter "${BASE_STATS}" "memory_items_total" "memory_items_total")

TEST_ID="E2E_TEST_MEMORY_${SECONDS}_$$"
WRITE_CONTENT="remember: the streamer is called Captain (${TEST_ID}_WRITE)"
READ_CONTENT="E2E_TEST_MEMORY_READ_${TEST_ID} who is the streamer called?"

publish_message "memory_write_${TEST_ID}" "human" "${WRITE_CONTENT}" "user:mem" "mem_user"

start=$SECONDS
write_ok=false
while (( SECONDS - start < 10 )); do
  sleep "${WAIT_AFTER_PUBLISH_S}"
  CUR_STATS=$(fetch_stats)
  CUR_WRITES=$(require_counter "${CUR_STATS}" "memory_writes_accepted" "memory_writes_accepted")
  CUR_ITEMS=$(require_counter "${CUR_STATS}" "memory_items_total" "memory_items_total")
  if (( CUR_WRITES >= BASE_WRITES + 1 )) && (( CUR_ITEMS >= BASE_ITEMS + 1 )); then
    write_ok=true
    break
  fi
done
if [ "${write_ok}" != "true" ]; then
  echo "FAIL: memory write did not register" >&2
  echo "BASE: ${BASE_STATS}" >&2
  echo "CUR: ${CUR_STATS:-}" >&2
  exit 1
fi

publish_message "memory_read_${TEST_ID}" "human" "${READ_CONTENT}" "user:memread" "mem_reader"

start_read=$SECONDS
read_ok=false
while (( SECONDS - start_read < CONNECT_TIMEOUT_S )); do
  sleep 1
  AFTER_STATS=$(fetch_stats)
  CUR_READS=$(require_counter "${AFTER_STATS}" "memory_reads_succeeded" "memory_reads_succeeded")
  if (( CUR_READS >= BASE_READS + 1 )); then
    read_ok=true
    break
  fi
done
if [ "${read_ok}" != "true" ]; then
  echo "FAIL: memory read did not register" >&2
  echo "BASE: ${BASE_STATS}" >&2
  echo "AFTER: ${AFTER_STATS:-}" >&2
  exit 1
fi

FINAL_STATS=${AFTER_STATS:-$(fetch_stats)}
FINAL_WRITES=$(require_counter "${FINAL_STATS}" "memory_writes_accepted" "memory_writes_accepted")
FINAL_ITEMS=$(require_counter "${FINAL_STATS}" "memory_items_total" "memory_items_total")
FINAL_READS=$(require_counter "${FINAL_STATS}" "memory_reads_succeeded" "memory_reads_succeeded")

if (( FINAL_WRITES < BASE_WRITES + 1 )) || (( FINAL_ITEMS < BASE_ITEMS + 1 )) || (( FINAL_READS < BASE_READS + 1 )); then
  echo "FAIL: expected counters to increase" >&2
  echo "BASE: ${BASE_STATS}" >&2
  echo "FINAL: ${FINAL_STATS}" >&2
  exit 1
fi

echo "PASS: memory pipeline ok (writes ${BASE_WRITES}->${FINAL_WRITES}, items ${BASE_ITEMS}->${FINAL_ITEMS}, reads ${BASE_READS}->${FINAL_READS})"
