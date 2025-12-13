# chat_gateway

Realtime chat gateway.

## Responsibilities
- Accept inbound messages from:
    - persona agents (bots)
    - humans (future)
- Broadcast messages to connected clients (WebSocket)
- Publish every broadcast message to `chat.firehose`
- Optional: persist chat logs for replay/debugging

## Interfaces
- Consumes: `chat.ingest`
- Produces: `chat.firehose`
- Uses schemas from: `packages/protocol/`

## Safety
- Enforces baseline content policy (e.g., blocklists/redaction) via `packages/safety/`
- Tags message origin (`human` vs `bot`)
