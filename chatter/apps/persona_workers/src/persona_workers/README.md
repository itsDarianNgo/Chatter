# persona_workers (package)

Core Python package for persona agents.

## Submodules
- `agent/` — agent runtime loop and state
- `memory/` — Mem0 adapter + scoping + hygiene rules
- `prompts/` — prompt templates and shared prompt fragments
- `policy/` — talk probability, anti-loop heuristics, safety gating
- `bus/` — pub/sub + stream adapters
- `schemas/` — pydantic models used internally (should mirror `packages/protocol/`)
- `telemetry/` — metrics/logging helpers
