# persona_workers/bus

Messaging adapters (pub/sub and streams).

## Responsibilities
- Subscribe to:
    - `stream.context`
    - `chat.firehose` (optional)
    - `chat.trends` (optional)
- Publish to:
    - `chat.ingest`

## Notes
Keep a small interface so we can swap Redis/NATS/Kafka without rewriting agents.
