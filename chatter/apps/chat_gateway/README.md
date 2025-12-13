# chat_gateway

Vertical-slice gateway for chatter. It consumes chat messages from Redis Streams, validates them against `ChatMessage` protocol schemas, applies safety redactions, broadcasts over WebSockets, and publishes the authoritative firehose stream.

## Running locally

- Set `REDIS_URL` (defaults to `redis://localhost:6379/0`).
- Start the app: `python -m apps.chat_gateway.src.main`.
- WebSocket endpoint: `ws://localhost:8080/ws`.
- Health: `GET /healthz`, Stats: `GET /stats`.

The gateway expects messages on `stream:chat.ingest` and will publish sanitized messages to `stream:chat.firehose`.
