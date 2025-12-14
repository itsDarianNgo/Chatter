# persona_workers (Turn B/C deterministic policy + LLM hooks)

A deterministic persona worker runtime that consumes chat events from `stream:chat.firehose`, applies a policy engine driven by room/persona configs, and publishes bot `ChatMessage` payloads back to `stream:chat.ingest`. Turn C introduces a pluggable generation layer that defaults to deterministic replies but can opt into stub or LiteLLM-backed responses via configuration.

## What it does
- Uses Redis Streams consumer groups on the firehose to read sanitized chat events.
- Maintains light in-memory state (recent messages, message-rate tracking, per-persona cooldowns, per-room budgets, dedupe cache).
- Applies a deterministic policy engine that combines cooldowns, room budgets, mention/hype bonuses, message-rate dampening, and a deterministic probability gate.
- Keeps a deterministic forced-response path for markers like `E2E_TEST_`, `E2E_TEST_BOTLOOP_`, or `E2E_MARKER_` (still blocks bot-origin and overly old events).
- Generates short single-line replies (no `@` mentions) with persona catchphrase flavor and optional emote sprinkling, always within max safety chars. When GENERATION_MODE is set to `stub` or `litellm`, replies flow through the prompt manifest plus provider config before post-processing.
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
- `GENERATION_MODE` (`deterministic` by default, set to `stub` or `litellm` to exercise the LLM pipeline)
- `LLM_PROVIDER_CONFIG_PATH=configs/llm/providers/stub.json`
- `PROMPT_MANIFEST_PATH=prompts/manifest.json`

## Notes
- Turn A intentionally skips LLM calls, Mem0, and drift/reflection prompts; Turn B/C add hooks for stub/litellm modes while keeping defaults deterministic and test-friendly.
- Safety rules enforce: no bot-to-bot reactions, per-persona cooldown, and per-room budget (default 5 bot messages per 10s).
- Only personas enabled in the room config are enrolled; if none are enabled the worker stays idle but healthy.
