# persona_workers

Autonomous persona agent workers (no orchestrator).

## Responsibilities
- Subscribe to `stream.context` and optionally `chat.firehose`
- Decide independently when to post (“Twitch spam physics”)
- Retrieve/store long-term persona memory using Mem0
- Evolve persona over time (drift/reflection loop)
- Publish generated messages to `chat.ingest`

## Interfaces
- Consumes: `stream.context`, `chat.firehose` (optional), `chat.trends` (optional)
- Produces: `chat.ingest`
- Uses schemas from: `packages/protocol/`
