# chat_gateway/src

Application source code for the chat gateway.

## Typical modules (suggested)
- websocket server & connection manager
- ingest consumer (stream/queue)
- broadcaster
- safety/middleware
- optional persistence adapter

All message shapes should come from `packages/protocol/`.
