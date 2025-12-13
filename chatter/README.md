# chatter

Persona-driven, Twitch-style chat that “watches” a live stream and reacts in real time.

## What lives where
- `apps/` — deployable services (gateway, context extraction, persona workers, UI)
- `packages/` — shared libraries and canonical schemas used across apps
- `configs/` — personas, rooms, moderation policy, shared prompt fragments
- `data/` — seeds and schema history
- `infra/` — local dev + deployment scaffolding
- `scripts/` — developer/ops scripts
- `docs/` — architecture notes, ADRs, runbooks
- `.github/` — CI workflows

## Core event channels (conceptual)
- `stream.context` — rolling “what’s happening on stream”
- `chat.ingest` — messages to be broadcast (bots + humans)
- `chat.firehose` — everything broadcasted (for agents/trends)
- `chat.trends` — rolling counters (velocity, emotes, mentions)

See `packages/protocol/` for canonical message schemas.
