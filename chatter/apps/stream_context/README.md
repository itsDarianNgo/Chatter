# stream_context

Produces a rolling snapshot of what’s happening on the live stream.

## Responsibilities
- Ingest stream audio (and optionally video frames)
- Generate:
    - transcript window (recent speech)
    - events (laugh/clutch/fail/chat-question/scene change)
    - keywords/topics
- Publish `stream.context` updates at a fixed cadence

## Interfaces
- Produces: `stream.context`
- Uses schemas from: `packages/protocol/`

## Notes
Keep outputs short and structured. Agents depend on small, stable context payloads.
