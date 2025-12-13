# chatter

## Project summary
`chatter` is a persona-driven, Twitch-style chat simulation that reacts to live streams in real time. The project is contract-driven: canonical schemas and configs define how persona agents, gateway services, and Mem0-backed memories interact, keeping behavior predictable while we iterate quickly.

## Key docs
- `docs/architecture/system_overview.md`
- `docs/architecture/protocols.md`
- `docs/architecture/persona_workers_spec.md`
- `docs/architecture/build_roadmap.md`

## Validation
- Run `npm run validate:artifacts` before opening a PR.
- This checks protocol schemas + fixtures, config schemas + example configs, and prompt-output schemas + fixtures using both Python and Ajv validators.
- CI runs the same command on pushes and pull requests; failures block merges.

## Repo layout
- `apps/` — services (gateway, persona workers, stream context, UI)
- `packages/protocol/` — canonical schemas
- `configs/` — room/persona/moderation configs, prompts, and config schemas
- `data/schemas/` — fixtures used by validators
- `scripts/ops/` — validation tools
- `infra/` — dev and deployment scaffolding
- `docs/` — architecture docs and notes

## Core event channels (conceptual)
- `stream.context` — rolling “what’s happening on stream”
- `chat.ingest` — messages to be broadcast (bots + humans)
- `chat.firehose` — everything broadcasted (for agents/trends)
- `chat.trends` — rolling counters (velocity, emotes, mentions)

See `packages/protocol/` for canonical message schemas.

## Roadmap alignment
Milestone 0 focuses on locking contracts and artifacts so worker implementation is straightforward and safe.
