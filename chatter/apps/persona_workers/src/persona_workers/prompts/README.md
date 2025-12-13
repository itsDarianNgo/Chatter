# persona_workers/prompts

Prompt templates used by persona workers.

## Prompt types
- Message generation (one short Twitch chat line)
- Durable memory extraction (JSON-only)
- Drift reflection (bounded JSON update + a few memories)

## Guidelines
- Keep prompts compact (latency + cost)
- Prefer structured outputs for memory operations
- Centralize shared fragments in `configs/prompts/`
