# web_ui

Twitch-like chat client UI.

## Responsibilities
- Connect to gateway WebSocket
- Render high-throughput chat (virtualized list)
- Display badges/colors/emotes
- Optional: viewer list, pinned messages, mod actions

## Interfaces
- Consumes messages broadcast by `apps/chat_gateway/`
- Uses schemas from `packages/protocol/`
