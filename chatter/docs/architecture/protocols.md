````md
# Protocols

This document defines the **core event channels**, **canonical message schemas**, **validation rules**, and **versioning expectations** for `chatter`.

It is the source of truth for how services communicate. All services should:
- **Produce** messages that conform to these schemas
- **Validate** messages at service boundaries
- **Reject or sanitize** invalid payloads (see Safety notes)

Related:
- System overview: `docs/architecture/system_overview.md`
- Canonical schema sources: `packages/protocol/`

---

## Message channels

`chatter` uses four primary channels (topic names are conceptual; transport-specific naming may vary).

| Channel | Producer(s) | Consumer(s) | Purpose |
|---|---|---|---|
| `stream.context` | `apps/stream_context` | `apps/persona_workers` | Rolling snapshot of what’s happening on stream |
| `chat.ingest` | `apps/persona_workers` (bots), future human input | `apps/chat_gateway` | Messages ready to broadcast |
| `chat.firehose` | `apps/chat_gateway` | `apps/persona_workers`, trends, logging, replay | Authoritative stream of what clients saw |
| `chat.trends` (optional) | trends job/service | `apps/persona_workers` | Rolling counters to shape “waves” |

### Channel ordering & delivery expectations
- **`chat.firehose` is authoritative**: if it wasn’t broadcast, it shouldn’t be treated as “seen by users”.
- Ordering is **best-effort**; consumers should tolerate mild reordering.
- Duplicate delivery is possible (depending on bus). Messages must be **idempotent** where practical (see `id` fields).

---

## Transport assumptions (abstract)
This spec is transport-agnostic. Whether you use Redis Streams, NATS, Kafka, etc., the following must hold:

- Messages are **UTF-8 JSON** objects.
- Each published record is one schema instance.
- Producers include a stable `schema_version` and `id`.
- Consumers must be able to parse/validate without additional context.

---

## Common conventions (applies to all schemas)

### Timestamps
- `ts` is an ISO-8601 string in UTC with milliseconds where available.
  - Example: `"2025-12-12T20:15:05.123Z"`

### IDs
- `id` is a globally unique identifier for the message/event.
- Recommended format: ULID or UUIDv7 (sortable IDs are helpful).

### Room scoping
- `room_id` is required on all messages.
- `room_id` should be stable and filesystem-safe.
  - Example: `"room:mychannel"`

### Origin & actor identifiers
- `origin` indicates where a message came from:
  - `"bot"` for persona workers
  - `"human"` for human input (future)
  - `"system"` for gateway/system-generated notices

- `user_id` and `display_name` represent the **visible speaker** in chat.
  - For bots: `user_id == persona name/handle`
  - For humans: `user_id` is a stable internal user key; `display_name` is what is shown

### Schema versioning
All messages include:
- `schema_name` (string)
- `schema_version` (string, semver-like, e.g. `"1.0.0"`)

---

## Safety and validation (global)

### Validation points (must)
- Producers validate before publish.
- `apps/chat_gateway` validates and enforces safety **before broadcasting**.
- Consumers validate on ingest and drop/ignore invalid records (with telemetry).

### Safety enforcement points (must)
- Persona workers should run lightweight pre-send checks.
- Gateway is final enforcement; it may:
  - drop message
  - redact parts
  - normalize/escape content
  - attach moderation metadata

Safety utilities should live in `packages/safety/`.

---

## Canonical schemas

Below are the “v1” schemas. The actual JSON Schema / bindings should be implemented in `packages/protocol/` and mirrored across languages.

### Diagram: channel relationships

```mermaid
flowchart LR
  SC[stream_context] -->|stream.context| PW[persona_workers]
  PW -->|chat.ingest| GW[chat_gateway]
  GW -->|chat.firehose| PW
  GW -->|websocket| UI[web_ui]
  TR[trends job] -->|chat.trends| PW
````

---

# Schema: StreamContext (`stream.context`)

A rolling snapshot of what’s happening on the stream, designed to be:

* **small** (agents read it frequently)
* **structured**
* **stable** over time

### Constraints

* `transcript_window` should cover ~20–60 seconds (configurable).
* Payload size should be kept small (recommendation: < 16 KB).
* Avoid including full raw transcripts for long periods; prefer summarization and keywords.

### Fields

| Field               | Type                       | Required | Notes                                           |
| ------------------- | -------------------------- | -------: | ----------------------------------------------- |
| `schema_name`       | string                     |        ✅ | `"StreamContext"`                               |
| `schema_version`    | string                     |        ✅ | `"1.0.0"`                                       |
| `id`                | string                     |        ✅ | unique id                                       |
| `ts`                | string                     |        ✅ | timestamp                                       |
| `room_id`           | string                     |        ✅ | scope                                           |
| `sequence`          | integer                    |        ✅ | monotonically increasing per room (best-effort) |
| `transcript_window` | array of TranscriptSegment |        ✅ | recent speech window                            |
| `events`            | array of StreamEvent       |        ✅ | may be empty                                    |
| `keywords`          | array of string            |        ✅ | compact topical cues                            |
| `summary`           | string                     |        ✅ | 1–3 lines, human-readable                       |
| `scene`             | string | null              |        ❌ | optional scene label                            |
| `debug`             | object | null              |        ❌ | optional internal info (avoid in prod)          |

#### TranscriptSegment

| Field        | Type          | Required | Notes                                  |
| ------------ | ------------- | -------: | -------------------------------------- |
| `t0_ms`      | integer       |        ✅ | relative start time (ms) within window |
| `t1_ms`      | integer       |        ✅ | relative end time (ms) within window   |
| `text`       | string        |        ✅ | transcript chunk                       |
| `speaker`    | string | null |        ❌ | optional                               |
| `confidence` | number        |        ❌ | 0–1 (if available)                     |

#### StreamEvent

| Field      | Type   | Required | Notes                  |
| ---------- | ------ | -------: | ---------------------- |
| `type`     | string |        ✅ | enum-like string       |
| `strength` | number |        ✅ | 0–1                    |
| `ts`       | string |        ✅ | event timestamp        |
| `meta`     | object |        ❌ | optional event details |

Recommended `type` values (extensible):

* `big_laugh`
* `fail`
* `clutch`
* `chat_question`
* `scene_change`
* `argument`
* `music_change`
* `silence`

### Example

```json
{
  "schema_name": "StreamContext",
  "schema_version": "1.0.0",
  "id": "01JH7Y0J1S0J2R1K9F1Y2YQZ9A",
  "ts": "2025-12-12T20:15:05.123Z",
  "room_id": "room:mychannel",
  "sequence": 1842,
  "transcript_window": [
    { "t0_ms": 0, "t1_ms": 4200, "text": "Alright chat, do we go left or right here?", "speaker": "streamer", "confidence": 0.92 }
  ],
  "events": [
    { "type": "chat_question", "strength": 0.85, "ts": "2025-12-12T20:15:04.900Z", "meta": { "question": "left or right" } }
  ],
  "keywords": ["decision", "route", "left", "right"],
  "summary": "Streamer asks chat to decide: left or right route.",
  "scene": "gameplay"
}
```

---

# Schema: ChatMessage (`chat.ingest`, `chat.firehose`)

A message intended to be displayed in chat. `chat.firehose` uses the same schema but represents what was actually broadcast.

### Constraints

* `content` is a single chat line; recommended max length: 1–200 chars (configurable).
* No multiline output.
* Avoid heavy nested objects (rendering performance).

### Fields

| Field            | Type                  | Required | Notes                                 |
| ---------------- | --------------------- | -------: | ------------------------------------- |
| `schema_name`    | string                |        ✅ | `"ChatMessage"`                       |
| `schema_version` | string                |        ✅ | `"1.0.0"`                             |
| `id`             | string                |        ✅ | unique id                             |
| `ts`             | string                |        ✅ | timestamp                             |
| `room_id`        | string                |        ✅ | scope                                 |
| `origin`         | string                |        ✅ | `"bot"` | `"human"` | `"system"`      |
| `user_id`        | string                |        ✅ | stable speaker identifier             |
| `display_name`   | string                |        ✅ | visible name                          |
| `content`        | string                |        ✅ | one line                              |
| `reply_to`       | string | null         |        ❌ | message id being replied to           |
| `mentions`       | array of string       |        ✅ | user_ids mentioned (may be empty)     |
| `emotes`         | array of EmoteToken   |        ✅ | parsed emotes (optional enhancement)  |
| `badges`         | array of string       |        ✅ | e.g. `["mod","vip"]`                  |
| `style`          | ChatStyle | null      |        ❌ | colors/format hints                   |
| `client_meta`    | object | null         |        ❌ | UI hints; gateway may strip/normalize |
| `moderation`     | ModerationMeta | null |        ❌ | results of checks/redaction           |
| `trace`          | TraceMeta | null      |        ❌ | observability fields                  |

#### EmoteToken

| Field      | Type    | Required | Notes                        |
| ---------- | ------- | -------: | ---------------------------- |
| `code`     | string  |        ✅ | `KEKW`                       |
| `provider` | string  |        ❌ | `twitch`/`bttv`/`7tv`/custom |
| `start`    | integer |        ❌ | char index start             |
| `end`      | integer |        ❌ | char index end               |

#### ChatStyle

| Field           | Type            | Required | Notes           |
| --------------- | --------------- | -------: | --------------- |
| `name_color`    | string          |        ❌ | hex             |
| `message_color` | string          |        ❌ | hex             |
| `effects`       | array of string |        ❌ | e.g. `["glow"]` |

#### ModerationMeta

| Field        | Type               | Required | Notes                       |
| ------------ | ------------------ | -------: | --------------------------- |
| `action`     | string             |        ✅ | `allow` | `redact` | `drop` |
| `reasons`    | array of string    |        ✅ | policy hits                 |
| `redactions` | array of Redaction |        ✅ | applied redactions          |

#### Redaction

| Field         | Type    | Required | Notes                         |
| ------------- | ------- | -------: | ----------------------------- |
| `kind`        | string  |        ✅ | e.g. `pii_email`, `pii_phone` |
| `start`       | integer |        ✅ | char index start              |
| `end`         | integer |        ✅ | char index end                |
| `replacement` | string  |        ✅ | e.g. `"[REDACTED]"`           |

#### TraceMeta (optional)

| Field        | Type    | Required | Notes              |
| ------------ | ------- | -------: | ------------------ |
| `producer`   | string  |        ❌ | service name       |
| `request_id` | string  |        ❌ | correlation        |
| `llm_ms`     | integer |        ❌ | generation latency |
| `mem_ms`     | integer |        ❌ | memory latency     |

### Example (bot message to `chat.ingest`)

```json
{
  "schema_name": "ChatMessage",
  "schema_version": "1.0.0",
  "id": "01JH7Y0M2KQ8T8G2A9F6G1VQ1N",
  "ts": "2025-12-12T20:15:06.010Z",
  "room_id": "room:mychannel",
  "origin": "bot",
  "user_id": "ClipGoblin",
  "display_name": "ClipGoblin",
  "content": "LEFT LEFT LEFT chat!!! KEKW",
  "reply_to": null,
  "mentions": [],
  "emotes": [{ "code": "KEKW", "provider": "twitch" }],
  "badges": ["vip"],
  "style": { "name_color": "#30D5C8", "effects": [] },
  "client_meta": null,
  "moderation": null,
  "trace": { "producer": "persona_workers", "llm_ms": 420, "mem_ms": 65 }
}
```

### Example (gateway-broadcast record on `chat.firehose`)

```json
{
  "schema_name": "ChatMessage",
  "schema_version": "1.0.0",
  "id": "01JH7Y0M2KQ8T8G2A9F6G1VQ1N",
  "ts": "2025-12-12T20:15:06.015Z",
  "room_id": "room:mychannel",
  "origin": "bot",
  "user_id": "ClipGoblin",
  "display_name": "ClipGoblin",
  "content": "LEFT LEFT LEFT chat!!! KEKW",
  "reply_to": null,
  "mentions": [],
  "emotes": [{ "code": "KEKW", "provider": "twitch" }],
  "badges": ["vip"],
  "style": { "name_color": "#30D5C8", "effects": [] },
  "client_meta": null,
  "moderation": { "action": "allow", "reasons": [], "redactions": [] },
  "trace": { "producer": "chat_gateway" }
}
```

---

# Schema: TrendsSnapshot (`chat.trends`) [Optional]

A small, frequently updated snapshot of what the chat is doing. This enables “social waves” without an orchestrator.

### Constraints

* Keep payload small (recommendation: < 4 KB).
* Publish at a short cadence (e.g., every 1–2 seconds).

### Fields

| Field            | Type                | Required | Notes                |
| ---------------- | ------------------- | -------: | -------------------- |
| `schema_name`    | string              |        ✅ | `"TrendsSnapshot"`   |
| `schema_version` | string              |        ✅ | `"1.0.0"`            |
| `id`             | string              |        ✅ | unique id            |
| `ts`             | string              |        ✅ | timestamp            |
| `room_id`        | string              |        ✅ | scope                |
| `window_s`       | integer             |        ✅ | rolling window size  |
| `msg_per_s`      | number              |        ✅ | velocity             |
| `top_tokens`     | array of TokenCount |        ✅ | includes emotes      |
| `top_mentions`   | array of TokenCount |        ✅ | most mentioned users |
| `bot_fraction`   | number              |        ✅ | 0–1 estimated        |
| `meta`           | object | null       |        ❌ | optional             |

#### TokenCount

| Field   | Type    | Required |
| ------- | ------- | -------: |
| `token` | string  |        ✅ |
| `count` | integer |        ✅ |

### Example

```json
{
  "schema_name": "TrendsSnapshot",
  "schema_version": "1.0.0",
  "id": "01JH7Y0R5KX6K0A1YV7A3XQH8D",
  "ts": "2025-12-12T20:15:07.000Z",
  "room_id": "room:mychannel",
  "window_s": 15,
  "msg_per_s": 7.4,
  "top_tokens": [
    { "token": "KEKW", "count": 32 },
    { "token": "LEFT", "count": 21 }
  ],
  "top_mentions": [
    { "token": "ClipGoblin", "count": 9 }
  ],
  "bot_fraction": 0.62,
  "meta": { "source": "gateway_trends" }
}
```

---

## Validation rules by service

### `apps/persona_workers` (producers of `chat.ingest`)

Must enforce:

* `schema_name`, `schema_version`, `id`, `ts`, `room_id`
* `origin="bot"`
* `content` is one line and within limits
* `mentions` list is consistent with `content` (best-effort)
* `style/badges` only from allowed persona config
* Do not include secrets or private data in `trace` or `client_meta`

Should enforce:

* local safety checks before publish (blocklist, doxxing patterns)
* attach `trace` fields for debugging (optional)

### `apps/chat_gateway` (consumer and re-producer)

Must enforce:

* validate incoming `chat.ingest` message
* run safety enforcement and set `moderation`
* normalize message for broadcast (strip invalid meta)
* publish exactly what was broadcast on `chat.firehose`

Should enforce:

* cap/batch broadcast under load (without breaking schema)

### `apps/web_ui` (consumer)

Must enforce:

* defensive parsing/validation
* never trust HTML/links; treat as plain text
* render missing optional fields safely

---

## Versioning & compatibility policy

### SemVer-style guidance

* Patch (`1.0.x`): clarifications, optional fields, backwards compatible changes
* Minor (`1.x.0`): additive fields that old consumers ignore
* Major (`2.0.0`): breaking changes (rename/remove fields, change semantics)

### Backward compatibility rules

* Producers may add optional fields at any time.
* Consumers must ignore unknown fields.
* Field removals or type changes require a major bump and a migration plan.

### Schema source of truth

* JSON Schema definitions live in `packages/protocol/jsonschema/`
* Language bindings live in `packages/protocol/python/` and `packages/protocol/typescript/`

---

## Extension points (planned)

* Add `SystemMessage` subtype (or `origin="system"` ChatMessage variants) for events like “agent joined”, “rate-limited”, etc.
* Add `Attachment` objects to ChatMessage (links, clip references) if needed.
* Add `StreamContext.visual_summary` if vision captions are enabled.

All extensions must remain small and safe to broadcast.
