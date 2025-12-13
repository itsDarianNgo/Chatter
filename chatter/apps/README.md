# apps

Deployable services and end-user applications.

Services communicate via pub/sub or streams and share schemas via `packages/protocol/`.

## Apps
- `chat_gateway/` — websocket gateway + broadcast + firehose publisher
- `stream_context/` — audio/video processing → `stream.context`
- `persona_workers/` — autonomous personas (LLM agents) + Mem0 + drift
- `web_ui/` — Twitch-like chat UI
