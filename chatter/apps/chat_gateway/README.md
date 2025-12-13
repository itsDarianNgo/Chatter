# chat_gateway

Vertical-slice gateway for chatter. It consumes chat messages from Redis Streams, validates them against `ChatMessage` protocol schemas, applies safety redactions, broadcasts over WebSockets, and publishes the authoritative firehose stream.

## Running locally

- Set `REDIS_URL` (defaults to `redis://localhost:6379/0`).
- Start the app: `python -m apps.chat_gateway.src.main`.
- WebSocket endpoint: `ws://localhost:8080/ws`.
- Health: `GET /healthz`, Stats: `GET /stats`.

The gateway expects messages on `stream:chat.ingest` and will publish sanitized messages to `stream:chat.firehose`.

### Trace metadata

- Preserves any incoming `trace.producer` (defaults to `"unknown"` if missing).
- Appends `"chat_gateway"` to `trace.processed_by` (initializes the array if absent).
- Adds `trace.gateway_ts` when not already present so downstream consumers can see processing time.
