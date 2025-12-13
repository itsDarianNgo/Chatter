# persona_workers/agent

Agent runtime and lifecycle.

## Responsibilities
- Maintain:
    - anchor persona (stable identity/voice)
    - drift state (evolving traits, mood, relationships)
    - live buffers (latest context + recent chat window)
- Run two loops:
    - fast “post loop” (probabilistic)
    - slow “drift/reflection loop” (persona evolution)
- Emit `chat.ingest` messages using `bus/`

## Key guarantees
- One output message per generation call
- Bounded message length (Twitch-like)
- Avoid bot-only feedback spirals (via `policy/`)
