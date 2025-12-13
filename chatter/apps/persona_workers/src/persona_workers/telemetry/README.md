# persona_workers/telemetry

Observability for agent workers.

## Responsibilities
- Structured logs (agent_id, room_id, tick timings)
- Metrics:
    - messages generated per agent
    - LLM latency / error rate
    - Mem0 latency / error rate
    - event-driven posting spikes
- Tracing hooks (optional)

Prefer shared helpers from `packages/observability/`.
