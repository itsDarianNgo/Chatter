# persona_workers (Turn A skeleton)

A minimal persona worker runtime that consumes chat events from `stream:chat.firehose`, applies deterministic policy triggers, and publishes bot `ChatMessage` payloads back to `stream:chat.ingest`. No LLM or Mem0 logic is present yet.

## What it does
- Uses Redis Streams consumer groups on the firehose to read sanitized chat events.
- Maintains light in-memory state (recent messages, per-persona cooldowns, per-room budgets, dedupe cache).
- Applies a deterministic trigger policy (markers like `E2E_TEST_`, `E2E_MARKER_`, or `@ClipGoblin`) with cooldown and budget checks.
- Generates short single-line replies and publishes valid `ChatMessage` documents with schema validation.
- Exposes FastAPI health and stats endpoints on port 8090.

## Running locally
```bash
export REDIS_URL=redis://localhost:6379/0  # override if needed
python -m apps.persona_workers.src.main
```

Key environment defaults live in `apps/persona_workers/src/settings.py`:
- `FIREHOSE_STREAM=stream:chat.firehose`
- `INGEST_STREAM=stream:chat.ingest`
- `ROOM_CONFIG_PATH=configs/rooms/demo.json`
- `PERSONA_CONFIG_DIR=configs/personas`
- `SCHEMA_CHAT_MESSAGE_PATH=packages/protocol/jsonschema/chat_message.schema.json`

## Notes
- Turn A intentionally skips LLM calls, Mem0, and drift/reflection prompts.
- Safety rules enforce: no bot-to-bot reactions, per-persona cooldown, and per-room budget (default 5 bot messages per 10s).
- Only personas enabled in the room config are enrolled; if none are enabled the worker stays idle but healthy.
