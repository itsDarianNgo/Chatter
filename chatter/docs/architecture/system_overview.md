````md
# System Overview

`chatter` is a multi-service system that produces a Twitch-style chat experience for a live stream, where many autonomous “persona agents” (LLM-driven chatters) watch the stream context and post messages in real time. The design prioritizes:

- **High-throughput, low-latency chat**
- **Believable personas with long-term continuity**
- **Safety-by-default** enforcement points
- **Scalable, modular services** that can be deployed independently
- **Clear contracts** between services via canonical schemas

This document explains how the services connect, what data flows between them, and where safety and memory live.

---

## Goals

### Primary goals
- Provide a chat UI and gateway that can handle “spammy” message rates without collapsing.
- Generate bot chatter that feels **distinct**, **reactive to the stream**, and **social** (piles on trends, recognizes names, develops rivalries).
- Maintain **persona continuity over time** using Mem0 (relationships, running jokes, preferences).
- Keep the architecture straightforward enough to evolve and scale.

### Non-goals (for initial versions)
- Full Twitch feature parity (bits, raids, subscriptions, etc.)
- Complex moderation tooling UI (we will enforce baseline policies; advanced tooling can be added later)
- Perfect “understanding” of video content (audio transcript-only can ship first)

---

## Core services and responsibilities

### `apps/chat_gateway/`
The real-time chat gateway. It is intentionally “dumb” about agent behavior.

**Responsibilities**
- Broadcast chat messages to connected WebSocket clients.
- Consume bot/human messages from `chat.ingest`.
- Publish everything that was broadcast to `chat.firehose` (for agents, trends, logging).
- Apply **baseline safety enforcement** (final gate before clients).
- Optionally persist chat logs.

**Why it exists**
- Centralizes connection management and broadcast, which must be stable under load.
- Provides the authoritative stream of “what viewers saw” (`chat.firehose`).

---

### `apps/stream_context/`
Produces a rolling snapshot of what’s happening on stream.

**Responsibilities**
- Ingest stream audio (and optionally video frames).
- Generate:
  - rolling transcript window (e.g., last 20–60 seconds)
  - structured events (e.g., `big_laugh`, `fail`, `clutch`, `chat_question`, `scene_change`)
  - keywords/topics
- Publish `stream.context` periodically.

**Why it exists**
- Agents need a compact, structured “now” context to react convincingly and cheaply.

---

### `apps/persona_workers/`
Autonomous persona agent workers. No orchestrator: spam is part of the experience.

**Responsibilities**
- Subscribe to `stream.context` (required).
- Optionally subscribe to `chat.firehose` (recommended for social behavior, with anti-loop policies).
- Optionally consume `chat.trends` (if enabled) to join “waves”.
- Independently decide when to post (probabilistic policy).
- Retrieve/store persona memory with Mem0.
- Run slow “drift/reflection” loop to evolve persona traits and relationships.
- Publish messages to `chat.ingest`.

**Why it exists**
- Isolates the heaviest compute and variability (LLM calls, memory ops) away from the gateway.
- Scales horizontally by adding more worker processes/pods.

---

### `apps/web_ui/`
Twitch-like chat client.

**Responsibilities**
- Connect to the gateway WebSocket.
- Render messages at high rates (virtualized list).
- Display username styling, badges, emotes.
- Provide resilient reconnection behavior.

---

## Shared packages

### `packages/protocol/`
Canonical event and message contracts for:
- `StreamContext` (`stream.context`)
- `ChatMessage` (`chat.ingest`, `chat.firehose`)
- `TrendsSnapshot` (`chat.trends`)

This is the “source of truth” for schemas. Services should validate against these contracts.

### `packages/safety/`
Shared safety utilities:
- blocklists, redaction patterns
- link normalization / risk flags
- shared minimal policy enforcement helpers

### `packages/observability/`
Shared logging/metrics/tracing conventions and helpers.

---

## Event channels (conceptual)

- `stream.context`
  - Produced by `stream_context`
  - Consumed by `persona_workers`

- `chat.ingest`
  - Produced by `persona_workers` (and later human input endpoints)
  - Consumed by `chat_gateway`

- `chat.firehose`
  - Produced by `chat_gateway` (everything broadcast)
  - Consumed by `persona_workers`, `devtools/replay`, trend counters, persistence

- `chat.trends` (optional)
  - Produced by a trends job (can be part of gateway or a small standalone service later)
  - Consumed by `persona_workers`

---

## High-level data flow

```mermaid
flowchart LR
  subgraph Stream["Live Stream (OBS/RTMP/Audio Device)"]
    A[Audio]:::stream
    V[Video Frames (optional)]:::stream
  end

  subgraph SC["apps/stream_context"]
    ASR[ASR: transcript window]:::svc
    EVT[Event detection]:::svc
    AGG[Context aggregator]:::svc
  end

  subgraph BUS["Message Bus (Redis/NATS/Kafka)"]
    CTX[(stream.context)]:::bus
    ING[(chat.ingest)]:::bus
    FHO[(chat.firehose)]:::bus
    TRD[(chat.trends - optional)]:::bus
  end

  subgraph PW["apps/persona_workers"]
    POL[Posting policy + anti-loop]:::svc
    LLM[LLM generation]:::svc
    MEM[Mem0 memory adapter]:::svc
    DRF[Drift/Reflection loop]:::svc
  end

  subgraph GW["apps/chat_gateway"]
    CONS[Consume chat.ingest]:::svc
    SAFE[Safety enforcement + tagging]:::svc
    WS[WebSocket broadcaster]:::svc
  end

  subgraph UI["apps/web_ui"]
    CHAT[Chat UI]:::ui
  end

  subgraph M0["Mem0 (external)"]
    M0API[(Memory store)]:::mem
  end

  A --> ASR
  V --> EVT
  ASR --> AGG
  EVT --> AGG
  AGG --> CTX

  CTX --> POL
  FHO --> POL
  TRD --> POL

  POL --> LLM
  MEM <--> M0API
  LLM --> ING
  DRF --> MEM
  LLM --> MEM

  ING --> CONS --> SAFE --> WS --> CHAT
  WS --> FHO

  classDef svc fill:#eef,stroke:#446,stroke-width:1px;
  classDef bus fill:#efe,stroke:#464,stroke-width:1px;
  classDef ui fill:#ffe,stroke:#664,stroke-width:1px;
  classDef stream fill:#fef,stroke:#646,stroke-width:1px;
  classDef mem fill:#eef,stroke:#446,stroke-dasharray:3 3;
````

---

## Message lifecycle (sequence view)

This shows a typical “moment on stream → bot reacts → users see it → bots observe it”.

```mermaid
sequenceDiagram
  autonumber
  participant Stream as Live Stream
  participant Context as stream_context
  participant Bus as Bus
  participant Agent as persona_worker (one agent)
  participant Mem0 as Mem0
  participant Gateway as chat_gateway
  participant UI as web_ui

  Stream->>Context: audio/video input
  Context->>Context: build transcript + events + keywords
  Context->>Bus: publish stream.context

  Bus-->>Agent: stream.context update
  Agent->>Mem0: search relevant memories (persona + relationships)
  Mem0-->>Agent: memory hits (+relations if enabled)
  Agent->>Agent: policy decides to post (probabilistic)
  Agent->>Agent: generate ONE short message (LLM)
  Agent->>Bus: publish chat.ingest (origin=bot)

  Bus-->>Gateway: chat.ingest message
  Gateway->>Gateway: safety checks + normalization + tagging
  Gateway->>UI: broadcast via WebSocket
  Gateway->>Bus: publish chat.firehose (authoritative broadcast record)

  Bus-->>Agent: chat.firehose (including its own message + reactions)
  Agent->>Mem0: add durable memory update (optional)
```

---

## Persona Workers: internal architecture

Persona workers are built to be scalable and stable under high volume. Each agent runs two loops:

* **Fast loop**: decides whether to post every few hundred ms (jittered).
* **Slow loop**: periodically “reflects” and updates persona drift + durable memories.

```mermaid
flowchart TB
  subgraph Agent["AgentWorker (single persona)"]
    BUF[Live buffers\n- latest StreamContext\n- recent chat window\n- trends snapshot]:::mod
    DEC[Decision policy\n(probability + boosts + dampeners)]:::mod
    RET[Mem0 retrieval\n(top-K memories)]:::mod
    GEN[LLM generate\nONE short message]:::mod
    OUT[Publish ChatMessage -> chat.ingest]:::mod
    EXT[Extract durable deltas\n(JSON-only)]:::mod
    ADD[Mem0 add\n(relationships/jokes/preferences)]:::mod
    DRIFT[Reflection loop\n(update drift state)]:::mod
  end

  BUF --> DEC --> RET --> GEN --> OUT
  GEN --> EXT --> ADD
  DRIFT --> ADD

  classDef mod fill:#eef,stroke:#446,stroke-width:1px;
```

### Key design rules for persona workers

* **No orchestrator**: multiple agents can speak simultaneously; message volume is part of the entertainment.
* **Anti-feedback**: agents should avoid spiraling by primarily reacting to:

    * stream context
    * human messages
    * mentions directed at them
      and downweighting bot-only chatter.
* **Memory hygiene**: store durable updates (facts/preferences/relationships), not raw spam.

---

## Memory strategy (Mem0)

### Scoping

To keep persona continuity clean and prevent “cross-contamination,” memories should be stored per persona scope.

Recommended scoping convention:

* `mem0_user_id = "room:{room_id}|agent:{agent_name}"`

Then store other entities as metadata:

* `metadata.other_user = "<viewer or agent referenced>"`
* `metadata.type = "relationship" | "catchphrase" | "preference" | "lore_event" | "persona_drift"`
* optionally: `metadata.confidence = low|med|high` for rumor control

### What we store (durable signals)

* **Relationships**: affinity/rivalry/respect, with reason and recency
* **Running jokes**: the “trigger” and the “phrase”
* **Preferences**: topics the persona loves/hates
* **Lore events**: the moment a meme was born (“we started saying X when Y happened”)
* **Drift snapshots**: periodic bounded updates to persona knobs

### What we avoid storing

* Raw chat spam unless it is clearly a durable event
* Unverified claims stated in chat (unless tagged low-confidence)
* Personal data or identifying info (must be redacted/blocked)

---

## Safety and moderation enforcement points

Safety is enforced in multiple layers (“defense in depth”):

1. **Persona workers (pre-send)**

    * Run lightweight checks on generated output
    * Enforce “one line only”, max length, and policy constraints
    * Avoid risky content and doxxing patterns early

2. **Chat gateway (final enforcement)**

    * This is the last stop before messages hit clients
    * Applies blocklists/redaction rules and origin tagging
    * Can drop or sanitize messages that violate policy

3. **Web UI (defensive rendering)**

    * Never trust input (even from our own services)
    * Escape/normalize links and suspicious payloads
    * Optional: warn or hide risky content

Shared safety logic should live in `packages/safety/` so behavior is consistent.

---

## Scalability and performance

### Key performance risks

* High message throughput (bots + humans)
* LLM latency spikes
* Memory latency spikes (Mem0)
* WebSocket broadcast fanout under load

### Mitigation strategies

* **Asynchronous bus** between workers and gateway (`chat.ingest`):

    * decouples generation from broadcast
* **Backpressure handling**:

    * the gateway can batch broadcasts or drop oldest messages if needed
* **Worker concurrency limits**:

    * cap parallel LLM calls per process
    * jitter agent ticks to avoid synchronized spikes
* **Thin retrieval**:

    * retrieve only top-K memories for fast loop
    * reserve heavier reflection operations for the slow loop
* **Trend snapshot decoupling**:

    * compute trends once per room and publish `chat.trends` rather than recomputing per agent

---

## Configuration model

Configuration is intended to be explicit, versionable, and overrideable per room.

* `configs/personas/`: persona roster and persona “anchors”
* `configs/rooms/`: per-room tuning (hype multiplier, bot-to-human bias)
* `configs/moderation/`: blocklists/redaction and allowed emotes
* `configs/prompts/`: shared prompt fragments and global rules

Persona drift is *runtime state* and should be stored either:

* in Mem0 as `persona_drift` items, or
* in a small local store/cache with periodic checkpointing into Mem0

---

## Observability and debugging

### What we should be able to answer quickly

* “Why did chat slow down?”
* “Which persona is spamming?”
* “Are bots reacting to bots too much?”
* “Is Mem0 causing latency?”
* “Did schemas change and break parsing?”

### Recommended telemetry per service

* Gateway: broadcast rate, connected clients, message drop counts
* Persona workers: per-agent posts/min, LLM latency, Mem0 latency, policy reasons for posting/not posting
* Stream context: ASR latency, publish cadence, event rates

Shared helpers should live in `packages/observability/`.

---

## Deployment topologies (options)

### Option A: One process runs many agents (good early)

* Pros: simpler, cheaper
* Cons: noisy neighbors (one agent’s failures can affect others)

### Option B: One pod per “agent group” or “room”

* Pros: isolates rooms, easier scaling
* Cons: more infrastructure overhead

### Option C: One pod per agent (maximum isolation)

* Pros: fault isolation and independent scaling
* Cons: highest ops overhead

Start with Option A for speed, then evolve based on load and reliability needs.

---

## Future extensions (planned-friendly)

* Add a dedicated `trends_service` producing `chat.trends`
* Add a moderation dashboard / review queue
* Add multi-room support with dynamic rosters
* Add richer vision-based event triggers (clip moments, UI recognition, etc.)
* Add chat replay + “time travel” debugging using `packages/devtools/replay`

---

## Related folders

* Schemas: `packages/protocol/`
* Safety: `packages/safety/`
* Worker internals: `apps/persona_workers/src/persona_workers/`
* Replay tools: `packages/devtools/replay/`
