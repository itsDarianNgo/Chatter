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

## Local demo (Milestone 1 slice)
- Start Redis + gateway + UI: `docker compose up --build`
- Open the UI at `http://localhost:5173` (connects to `ws://localhost:8080/ws`)
- Optional load: `python apps/tools/stub_publisher/publish.py --rate 20`

## Milestone 2 E2E
- persona_workers now runs in docker compose and exposes `http://localhost:8090/healthz` for stats and health.
- One-command local test sweep: `npm run compose:test:e2e` (brings up compose, waits for services, runs all E2E tests, then tears down).
- Alternatively:
  - `npm run compose:up` (or `docker compose up --build`)
  - `bash scripts/integration/wait_for_services.sh`
  - `npm run test:e2e:all`
  - `npm run compose:down`
- Windows users should run the bash scripts via Git Bash or WSL; a PowerShell helper is available at `scripts/integration/compose_test_e2e.ps1`.

## Core event channels (conceptual)
- `stream.context` — rolling “what’s happening on stream”
- `chat.ingest` — messages to be broadcast (bots + humans)
- `chat.firehose` — everything broadcasted (for agents/trends)
- `chat.trends` — rolling counters (velocity, emotes, mentions)

See `packages/protocol/` for canonical message schemas.

## Roadmap alignment
Milestone 0 focuses on locking contracts and artifacts so worker implementation is straightforward and safe.
