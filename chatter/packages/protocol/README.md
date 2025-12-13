# protocol

Canonical message/event contracts across the system.

## Responsibilities
- Define schemas for:
    - `StreamContext` (`stream.context`)
    - `ChatMessage` (`chat.ingest`, `chat.firehose`)
    - `TrendsSnapshot` (`chat.trends`)
- Provide generated/handwritten bindings for:
    - JSON Schema (language-agnostic)
    - Python (Pydantic/dataclasses)
    - TypeScript (types/zod/etc.)

## Rule
Update protocol first. All apps mirror/consume these schemas.
