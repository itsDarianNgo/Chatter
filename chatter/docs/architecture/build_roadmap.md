# Build Roadmap

This document describes what to build and in what order for `chatter`, with milestone deliverables, dependencies, and definition-of-done (DoD) checkpoints.

Related:
- `docs/architecture/system_overview.md`
- `docs/architecture/protocols.md`
- `docs/architecture/persona_workers_spec.md`

---

## Guiding principles
- Keep services decoupled by `packages/protocol/` schemas.
- Keep the gateway fast and boring; push variability to persona workers.
- Ship a thin vertical slice early (end-to-end flow) and iterate.
- Prefer “safe-by-default” and defense-in-depth.
- Build for observability from day one (logs + basic metrics).

---

## Milestone 0 — Repo & contracts (foundation)

### Deliverables
- Repo structure created (apps/, packages/, configs/, etc.)
- Canonical schemas drafted in `packages/protocol/` (JSON Schema + bindings)
- Safety policy config skeleton in `configs/moderation/`
- Basic persona config examples in `configs/personas/`
- Docs baseline:
    - `system_overview.md`
    - `protocols.md`
    - `persona_workers_spec.md`
    - this `Build Roadmap`

### DoD
- Every service agrees on message shape and fields.
- At least one example JSON instance per schema passes validation.
- Versioning rules documented and understood.

---

## Milestone 1 — Vertical slice (fake context → fake agents → real UI)

Goal: see messages in the UI via the real gateway, even if agents are stubbed.

### Build order
1. **Chat Gateway**
    - WebSocket broadcast server
    - Consume `chat.ingest` (from a simple publisher)
    - Publish `chat.firehose` (everything broadcast)
    - Basic validation and safety stub

2. **Web UI**
    - Connect to WebSocket
    - Render messages (virtualized list)
    - Basic styling for users/badges/colors

3. **Stub Persona Publisher**
    - Simple script that publishes test `ChatMessage` events to `chat.ingest`

### DoD
- You can run gateway + UI locally and see messages appear.
- Messages are validated against `packages/protocol/`.
- Gateway publishes `chat.firehose` with identical `id` and correct metadata.

---

## Milestone 2 — Persona Workers MVP (no drift, minimal memory)

Goal: bots speak autonomously based on a dummy `stream.context`, but memory is basic.

### Build order
1. **Persona Worker runtime**
    - Load roster from `configs/personas/`
    - Subscribe to `stream.context`
    - Compute `p_post` and generate one-line messages
    - Publish to `chat.ingest`
    - Basic anti-loop handling (even if firehose disabled initially)

2. **Stream Context Stub**
    - Publisher that emits fake `StreamContext` payloads on a cadence
    - Include events and keywords for agents to react to

3. **Mem0 integration (minimal)**
    - Retrieval: top-K “my running jokes” and “my preferences”
    - Writes: store only a simple `persona_note` type for now

### DoD
- Agents post without centralized orchestration.
- Output is one-line, within max chars, no crashes under 10–50 agents.
- Mem0 read/write works end-to-end (even if simplistic).

---

## Milestone 3 — Real stream context (audio transcript first)

Goal: agents react to real stream audio.

### Build order
1. **Stream Context Service (audio only)**
    - Ingest audio source
    - Produce rolling transcript window + keywords + summary
    - Emit `chat_question` and simple event heuristics when possible

2. **Persona Workers consume real context**
    - Replace stub context with real `stream.context`
    - Tune talkativeness and event boosts

### DoD
- With live audio, stream_context publishes stable updates.
- Agents react to what’s said with low latency (seconds).
- Context payload stays small and consistent.

---

## Milestone 4 — Memory hygiene + durable extraction (quality jump)

Goal: stop memory pollution and make personas consistent over sessions.

### Build order
1. **Durable memory extraction prompt**
    - After each agent message, run extraction JSON prompt
    - Store structured updates in Mem0 only (relationships, jokes, preferences)

2. **Scoped memory conventions**
    - Enforce `mem0_user_id = room:{room_id}|agent:{agent_name}`
    - Ensure metadata keys (`type`, `other_user`, `confidence`, etc.) are consistent

3. **Human-first retrieval**
    - If firehose is enabled: bias agents toward human messages
    - Prevent bot-only spirals via policy dampening

### DoD
- After 30 minutes of spam, memory remains clean (no random “facts”).
- Agents recall recurring jokes and relationships consistently.
- Bot-only feedback loops are rare and bounded.

---

## Milestone 5 — Persona drift/reflection loop (long-term persona evolution)

Goal: personas evolve gradually and become “characters.”

### Build order
1. **Reflection prompt + drift state**
    - Periodic drift update with bounded changes
    - Store drift snapshots as durable memory

2. **Relationship shaping**
    - Use extraction deltas to adjust who they like/tease
    - Retrieval queries include relationship memories for mentioned users

3. **Tuning tools**
    - Per-room and per-persona tuning knobs in `configs/rooms/` and `configs/personas/`

### DoD
- Personas change measurably over time but remain recognizable.
- Drift stays within bounds; no wild personality flips.
- Relationships persist across sessions.

---

## Milestone 6 — Trends and “waves” (optional, improves Twitch feel)

Goal: make chat feel socially coherent without an orchestrator.

### Build order
1. **Trends snapshot producer**
    - Compute msg velocity, top tokens/emotes, bot_fraction, top mentions
    - Publish `chat.trends` every 1–2 seconds

2. **Agent trend participation**
    - Boost `p_post` and content selection based on trends
    - Make behavior depend on persona traits (meme_level, helpfulness)

### DoD
- Chat exhibits visible “waves” (pile-ons) during hype moments.
- Agents don’t all copy each other; persona variation remains.

---

## Milestone 7 — Safety hardening & ops readiness

Goal: production-friendly behavior and guardrails.

### Build order
- Expand blocklists and redaction patterns (`configs/moderation/`)
- Add message dropping/redaction audits in gateway
- Add metrics dashboards and basic runbooks
- Add replay tooling for deterministic debugging

### DoD
- Clear logs/metrics for latency and error attribution.
- Ability to replay a session’s context + chat deterministically.
- Safety incidents are detectable and containable.

---

## Milestone 8 — Vision context (optional)

Goal: react to what’s on screen (scene changes, wins/losses, UI cues).

### Build order
- Frame sampling + captions
- Event detection improvements (clutch/fail from visuals)
- Extend `StreamContext` carefully (add optional fields)

### DoD
- Agents react to visual moments that aren’t spoken aloud.
- Payload sizes remain bounded.

---

## Appendix: Recommended first vertical slice

If you do only one thing first:
1) Gateway + UI end-to-end
2) Stub context publisher
3) Persona workers generating messages
4) Mem0 read/write minimal

This proves the entire pipeline and keeps iteration loops fast.
