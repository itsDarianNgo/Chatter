# ADR 0001: Bus Selection

## Status
Accepted

## Context
We need a simple, local-friendly event bus for the MVP that can move chat messages with reasonable throughput and at-least-once delivery while remaining easy to operate in CI and Docker Compose. Redis Streams provide ordered message retention, consumer groups, and straightforward administration without requiring extra infrastructure.

## Decision
Use Redis Streams as the message bus for the vertical slice. We will map logical channels to these stream keys:

- `stream:chat.ingest` for inbound chat messages
- `stream:chat.firehose` for messages that were validated, safety-checked, and broadcast

## Consequences
- At-least-once delivery means duplicates are possible; downstream consumers should deduplicate using the `id` field.
- Local development is easy with a single Redis container, and throughput is sufficient for early testing.
- Future migrations to NATS or Kafka remain possible if we outgrow Redis Streams.
