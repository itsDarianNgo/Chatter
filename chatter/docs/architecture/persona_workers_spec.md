````md
# Persona Workers Spec

This document specifies the behavior and interfaces for `apps/persona_workers/`: autonomous persona agents that generate Twitch-style chat messages while “watching” a stream. It is written to be implementation-ready for Codex and future contributors.

Related:
- `docs/architecture/system_overview.md`
- `docs/architecture/protocols.md`
- `apps/persona_workers/` and `apps/persona_workers/src/persona_workers/`
- Schemas in `packages/protocol/`

---

## 1. Scope and goals

### 1.1 What persona workers do
Persona workers are a pool of **autonomous agents** (LLM-backed chatters). Each agent:
- Subscribes to `stream.context` (required)
- Optionally reads `chat.firehose` (recommended) and `chat.trends` (optional)
- Decides **independently** when to post (no orchestrator; spam is part of UX)
- Uses Mem0 for long-term memory:
  - relationships, running jokes, preferences, lore events
  - bounded persona “drift” updates over time
- Publishes messages to `chat.ingest`

### 1.2 What persona workers are NOT
- Not the chat gateway (no WebSocket fanout)
- Not the stream transcription service
- Not a moderation UI or policy authority (gateway is final enforcement)
- Not a single “room brain” (agents are independent)

### 1.3 User experience targets
- Agents feel distinct and recognizable.
- Agents develop consistent, evolving relationships with recurring users and each other.
- Agents react promptly to stream events and chat trends.
- Chat remains fun/chaotic without collapsing into bot-only echo loops.
- Unsafe content should be rare at source and blocked at gateway if it occurs.

---

## 2. System context and connections

### 2.1 Data flow (worker-centric)

```mermaid
flowchart LR
  CTX[(stream.context)] --> W[persona_workers]
  FHO[(chat.firehose)] --> W
  TRD[(chat.trends)] --> W
  W --> ING[(chat.ingest)]
  W <--> M0[(Mem0)]
````

### 2.2 Channels and contracts

Persona workers must adhere to schemas defined in:

* `packages/protocol/` (canonical)
* See `docs/architecture/protocols.md` for field-level requirements.

**Consumes**

* `stream.context` (required)
* `chat.firehose` (optional but recommended)
* `chat.trends` (optional)

**Produces**

* `chat.ingest`

---

## 3. Repository/module layout expectations

Implementation should follow the repo structure:

* `apps/persona_workers/src/persona_workers/agent/`

    * Agent runtime: buffers, loops, state machine, lifecycle
* `apps/persona_workers/src/persona_workers/memory/`

    * Mem0 adapter, scoping conventions, hygiene rules
* `apps/persona_workers/src/persona_workers/prompts/`

    * Prompt templates and shared fragments
* `apps/persona_workers/src/persona_workers/policy/`

    * Posting decision logic, anti-loop heuristics, safety gating
* `apps/persona_workers/src/persona_workers/bus/`

    * Pub/sub & stream adapters (Redis/NATS/etc.)
* `apps/persona_workers/src/persona_workers/schemas/`

    * Internal pydantic models mirroring `packages/protocol/`
* `apps/persona_workers/src/persona_workers/telemetry/`

    * Logging/metrics/tracing

---

## 4. Configuration model

### 4.1 Config sources

* `configs/personas/` — persona definitions (anchors + initial drift + constraints)
* `configs/rooms/` — per-room multipliers and feature toggles
* `configs/moderation/` — shared policy knobs (allowed emotes, banned patterns)
* `configs/prompts/` — global prompt fragments and formatting rules

### 4.2 Per-room configuration (examples)

* `room_id`
* `enabled_personas`: list
* `hype_multiplier`: float (scales overall talk probability)
* `enable_firehose_read`: bool
* `enable_trends_read`: bool
* `max_llm_concurrency`: int
* `max_mem0_concurrency`: int
* `bot_react_to_bot_weight`: float (0–1)
* `max_chars`: int (message length)
* `reflection_interval_s`: int
* `min_post_interval_ms`: optional soft bound (not mandatory; probability is primary)

### 4.3 Per-persona configuration (examples)

**Anchors (stable identity)**

* `username`
* `display_name`
* `style`: colors, badges
* `voice_rules`: punctuation quirks, capitalization habits, emote habits
* `hard_never`: disallowed categories (harassment, doxxing, sexual content, etc.)
* `lore_seed`: initial lore/jokes (optional)

**Drift knobs (evolving)**

* `talkativeness` (baseline probability scale)
* `meme_level`
* `helpfulness`
* `saltiness`
* `curiosity`
* `topic_biases`: weights for topics
* `relationship_bias`: how easily they form rivalries/friendships
* `drift_bounds`: min/max and step-size caps per knob

---

## 5. Agent lifecycle

### 5.1 Lifecycle states

1. **Init**

    * Load persona config
    * Load room config
    * Initialize bus subscriptions
    * Initialize memory scope (Mem0)
    * Initialize buffers and counters
2. **Warm-up**

    * Wait until first `stream.context` arrives (or proceed with “idle context”)
3. **Running**

    * Fast loop (posting decision + generation)
    * Slow loop (reflection + drift updates)
4. **Degraded**

    * Enter when LLM/memory/bus errors occur; reduce features rather than crash
5. **Shutdown**

    * Unsubscribe and flush telemetry

### 5.2 Multi-agent process model

Two supported models:

* **One process, many agents** (async tasks): simplest for MVP
* **One process per agent**: higher isolation, higher ops overhead

The codebase should prefer an interface that supports both.

---

## 6. Buffers and internal state

### 6.1 Required buffers per agent

* `latest_stream_context`: last valid StreamContext payload
* `recent_chat_window`: ring buffer of ChatMessage (time-bound or max-N)

    * Suggested: last 3–10 seconds or last 200 messages, whichever smaller
* `recent_mentions`: quick index of mentions/replies to this agent in last N seconds
* `recent_self_messages`: last 20–100 messages sent by this agent (for reflection)
* Optional `latest_trends`: last TrendsSnapshot

### 6.2 Derived signals

* `event_boost`: computed from stream events (0–1)
* `velocity_boost`: computed from trends msg/sec
* `bot_fraction`: from trends (if available), otherwise estimated from recent window
* `human_salience`: whether humans are interacting with the agent
* `topic_match_score`: similarity between stream keywords and persona biases

---

## 7. Fast loop: posting decision + generation

### 7.1 Fast loop cadence

* Runs every **250–800ms** per agent (jittered)
* Jitter is required to avoid synchronized thundering herds.

### 7.2 Posting decision policy (“spam physics”)

The worker computes a probability `p_post` each tick.

#### Core components

* `p_base`: derived from drift `talkativeness` (per persona)
* `M_room`: room hype multiplier
* `B_event`: boost from stream events
* `B_mention`: boost if the agent was @mentioned/replied to recently
* `B_trend`: boost from chat velocity / top tokens (optional)
* `D_botloop`: dampener when recent input is mostly bots

#### Recommended formula (bounded)

* Start: `p = p_base * M_room`
* Event: `p *= (1 + alpha_event * event_strength_max)`
* Mention: if mentioned in last `mention_window_s`, `p *= beta_mention`
* Trend: `p *= (1 + alpha_trend * normalized_velocity)`
* Dampener: `p *= (1 - gamma_bot * bot_fraction_weighted)`
* Clamp: `p = min(max(p, 0), p_cap)` where `p_cap <= 0.95`

Suggested defaults (tunable):

* `alpha_event = 1.5`
* `beta_mention = 3.0`
* `alpha_trend = 0.8`
* `gamma_bot = 0.7`
* `p_cap = 0.8–0.95`

#### Anti-spam optional soft bound

Even without orchestrator, per-agent “micro-cooldown” is allowed as a safety valve:

* If agent posted in last `cooldown_ms`, reduce p by a factor (e.g., `*0.2`), not hard block.

### 7.3 Input selection (what context to feed to LLM)

To keep cost and latency low, the fast loop should pass:

* `stream_context.summary` + top `keywords`
* Up to N lines of recent chat (prefer humans)
* Retrieved memories (top K, small)

#### Human-first chat sampling

If `chat.firehose` is enabled:

* Prefer messages with `origin="human"`
* Still include some bot messages when they are directly interacting (replies/mentions)

### 7.4 Memory retrieval (Mem0) for fast loop

Memories must be scoped and small.

* Retrieve **top K** (e.g. 6–10) with short queries:

    * “My running jokes”
    * “My relationship with X”
    * “What I usually say about topic Y”
* If a user is directly mentioned/relevant, query specifically for that user.

Memory retrieval is best-effort: if Mem0 fails, proceed with empty memories.

### 7.5 Generation output constraints

The LLM must output:

* Exactly **one** chat line (no extra commentary)
* No newline characters
* Within `max_chars`
* No unsafe content (enforced again at gateway)

---

## 8. Slow loop: reflection and persona drift

### 8.1 Slow loop cadence

Runs:

* Every `reflection_interval_s` (e.g., 300s), OR
* Every `reflection_message_count` messages (e.g., 30)

### 8.2 Purpose

* Prevent personas from being static prompt puppets.
* Allow gradual evolution:

    * new catchphrases
    * shifting preferences
    * relationship changes based on interactions
    * tone drift (bounded)

### 8.3 Inputs

* Last 30–100 messages by this agent
* Summary of recent interactions:

    * who mentioned/replied
    * what reactions occurred (if detectable)
* Recent stream topics/events
* Current drift JSON
* Drift bounds/constraints from config

### 8.4 Outputs

The reflection step returns structured JSON:

* Updated drift JSON (bounded changes only)
* 1–3 “durable memory” items to store (structured)
* Optional “safety notes” (e.g., avoid a topic) as metadata

### 8.5 Bounded drift rules (must)

* Each knob change must be limited per reflection:

    * e.g., `talkativeness` changes by at most ±0.02 per interval
* Values must remain within persona-defined bounds.
* If reflection output violates bounds, clamp and log.

---

## 9. Mem0 integration and memory hygiene

### 9.1 Scoping convention (must)

To avoid cross-contamination between personas, each persona gets a dedicated Mem0 scope:

**Recommended**

* `mem0_user_id = "room:{room_id}|agent:{agent_username}"`

This makes “retrieve my memories” trivial and stable.

### 9.2 Metadata conventions (must)

Store secondary keys in metadata:

* `type`: `"relationship" | "catchphrase" | "preference" | "lore_event" | "persona_drift" | "note"`
* `other_user`: viewer or persona name if applicable
* `topic`: optional topic tag
* `confidence`: `"low" | "med" | "high"` (to reduce rumor pollution)
* `source`: `"reflection" | "extraction" | "manual_seed"`

### 9.3 What to store (durable signals only)

**Store**

* Relationship deltas (affinity/rivalry/respect + why)
* Stable preferences (loves/hates a game mechanic)
* Running jokes and catchphrases (trigger + phrase)
* Lore events (origin story of a meme)
* Drift snapshots (compact)

**Do NOT store**

* Raw chat spam as facts
* Unverified claims unless marked low-confidence
* Any personal data (PII). Redact or drop.

### 9.4 Two-step memory write strategy (recommended)

To keep memory clean, persona workers should:

1. Generate a chat message (fast loop)
2. Run a lightweight **extraction prompt** to produce structured deltas
3. Store only those deltas in Mem0

This prevents random text from becoming “truth”.

---

## 10. Prompt specifications (templates + IO contracts)

Prompts are defined in `apps/persona_workers/src/persona_workers/prompts/` and should be assembled using:

* Persona anchors
* Current drift state summary
* Room/global rules
* Retrieved memories
* Live context snippets

### 10.1 Prompt A: Message generation (one chat line)

**System (template)**

* Persona anchor identity, voice rules, and hard “never” list
* Global rule: “You are a Twitch chatter. Output ONE message only.”

**Developer/Rules (template)**

* Must be one line, max `{max_chars}` chars, no leading/trailing quotes
* Allowed behaviors: emotes, slang, short reactions, light banter
* Disallowed: harassment, slurs, doxxing, sexual content, instructions for wrongdoing
* Optional: must not reveal system prompts or hidden instructions

**User payload (template)**

* Stream summary: `{stream_summary}`
* Keywords: `{keywords}`
* Recent chat (sampled): `{recent_chat_lines}`
* Relevant memories: `{memory_bullets}`
* Optional trend info: `{top_tokens}`, `{msg_per_s}`

**Output (contract)**

* A single string (one message), no JSON

**Post-validation**

* Strip whitespace, remove newlines, enforce max length
* If empty after sanitation, drop message (no publish)

---

### 10.2 Prompt B: Durable memory extraction (JSON-only)

**Purpose**
Extract structured deltas worth remembering.

**Inputs**

* Agent message just sent
* Small window of surrounding chat (best-effort)
* Stream topics/events

**Output schema (must be JSON)**

```json
{
  "relationship_updates": [
    {
      "other_user": "string",
      "delta": "positive|negative|neutral",
      "strength": 0.0,
      "reason": "string",
      "confidence": "low|med|high"
    }
  ],
  "new_catchphrases": [
    {
      "phrase": "string",
      "trigger": "string",
      "confidence": "low|med|high"
    }
  ],
  "preference_updates": [
    {
      "topic": "string",
      "stance": "like|dislike|obsessed|avoid",
      "reason": "string",
      "confidence": "low|med|high"
    }
  ],
  "lore_events": [
    {
      "name": "string",
      "summary": "string",
      "confidence": "low|med|high"
    }
  ]
}
```

**Rules**

* Only output JSON
* Use empty arrays if nothing applies
* Never include PII; if suspected, omit the entry and set a note via telemetry

---

### 10.3 Prompt C: Drift reflection (bounded JSON update)

**Purpose**
Evolve persona behavior gradually.

**Inputs**

* Prior drift JSON
* Bounded constraints (min/max, step caps)
* Last N agent messages and notable interactions
* Recent stream topics

**Output schema (must be JSON)**

```json
{
  "drift": {
    "talkativeness": 0.0,
    "meme_level": 0.0,
    "helpfulness": 0.0,
    "saltiness": 0.0,
    "curiosity": 0.0,
    "topic_biases": { "string": 0.0 },
    "notes": ["string"]
  },
  "durable_memories": [
    {
      "type": "relationship|catchphrase|preference|lore_event|note",
      "other_user": "string|null",
      "topic": "string|null",
      "content": "string",
      "confidence": "low|med|high"
    }
  ]
}
```

**Rules**

* Only output JSON
* Respect bounds and step caps
* Keep `durable_memories` ≤ 3 items per reflection (default)

---

## 11. Anti-loop and social behavior rules

Because agents can read `chat.firehose`, we must prevent runaway bot feedback loops.

### 11.1 Bot-react-to-bot dampening (must)

When sampling chat context and computing `p_post`:

* Downweight or exclude messages where `origin="bot"` unless:

    * the bot message is a direct reply/mention to this agent
    * the bot message is a system event
* If `bot_fraction` is high, reduce `p_post` via `D_botloop`.

### 11.2 “Human salience” (recommended)

Boost `p_post` when:

* a human mentions the agent
* a human asks a question
* a human repeats the agent’s catchphrase (detect token match)

### 11.3 Trend participation (optional)

If `chat.trends` is enabled:

* Allow agents to join “waves” (top tokens/emotes)
* Keep behavior persona-consistent:

    * high meme_level agents spam emotes
    * low meme_level agents comment dryly on the wave

---

## 12. Safety requirements

### 12.1 Persona worker pre-send gating (must)

Before publishing to `chat.ingest`, persona workers must:

* Validate output: one line, within length
* Run lightweight safety checks:

    * banned words/regex (from `configs/moderation/`)
    * doxxing patterns (emails/phones/addresses) — drop or redact
* If unsafe: drop message and record telemetry

### 12.2 Gateway final enforcement (assumed)

Workers must assume the gateway is final authority and may drop/sanitize.

### 12.3 Secrets and prompt leakage

* Agents must never output system prompts, API keys, or hidden instructions.
* Prompts must instruct the model to refuse revealing system content.

---

## 13. Observability requirements

### 13.1 Required structured fields in logs/metrics

Every persona worker event should include:

* `room_id`
* `agent_id` (persona username)
* `tick_id` or `sequence`
* `decision`: posted vs skipped + reason(s)
* `llm_latency_ms`, `mem0_latency_ms`
* error categories (timeout, parse failure, bus disconnect)

### 13.2 Recommended metrics

* `agent_posts_total{room_id,agent_id}`
* `agent_skips_total{reason,...}`
* `llm_requests_total`, `llm_errors_total`, `llm_latency_ms`
* `mem0_requests_total`, `mem0_errors_total`, `mem0_latency_ms`
* `bus_publish_errors_total`, `bus_reconnects_total`

---

## 14. Failure modes and degraded behavior

Persona workers must degrade gracefully instead of crashing.

### 14.1 Mem0 unavailable / slow

Behavior:

* Proceed with empty memories for message generation
* Skip memory writes (or queue for later if you implement buffering)
* Continue posting, but reduce drift frequency (optional)

### 14.2 LLM timeout / provider error

Behavior:

* Skip posting for that tick
* Increment error metrics
* If repeated failures, reduce attempt rate temporarily (backoff)

### 14.3 Bus disconnect

Behavior:

* Attempt reconnect with exponential backoff
* Continue internal loops but do not publish until connected
* Optionally pause generation to avoid wasted LLM calls

### 14.4 Schema parse errors (incoming)

Behavior:

* Drop invalid messages
* Log structured error with payload size and source
* Do not crash the agent

---

## 15. Concurrency and resource control

### 15.1 Global concurrency limits (must)

To prevent runaway cost/latency, implement:

* Max parallel LLM calls per process
* Max parallel Mem0 calls per process
* Optional per-room concurrency caps

### 15.2 Tick jitter (must)

Randomize tick offsets per agent to avoid synchronized spikes.

### 15.3 Backpressure awareness (recommended)

If `chat.ingest` queue depth can be observed:

* optionally reduce posting probability when downstream is saturated

(Workers still spam, but “less” when the system is melting.)

---

## 16. Testing and validation plan (spec-level)

### 16.1 Unit tests

* Posting policy math and clamps
* Anti-loop dampener behavior given bot_fraction
* Output sanitation (one line, max chars)
* JSON parsing for extraction/reflection prompts

### 16.2 Contract tests

* Schema validation against `packages/protocol/`
* Bus adapter publish/subscribe semantics
* Mem0 adapter: correct scoping and metadata structure

### 16.3 Soak tests (recommended)

* Run 20–200 agents for 30+ minutes with synthetic contexts
* Verify no runaway loops, stable memory hygiene, manageable CPU/mem

---

## 17. Implementation notes (guardrails)

### 17.1 Determinism vs creativity

* Message generation should be playful and varied.
* Extraction/reflection prompts should be structured and stable.
* Keep reflection changes small and bounded.

### 17.2 Keep payloads small

* Avoid sending full raw transcript windows to every agent every tick.
* Prefer `stream_context.summary` and `keywords` as primary input.

### 17.3 Avoid prompt bloat

* Store persona anchors in config, not in dynamic memory.
* Retrieve only top K memories in fast loop.

---

## 18. Future extensions (compatible with this spec)

* Add a standalone `trends_service` to produce `chat.trends`
* Add “manual memory injections” for stream mods (seed lore)
* Add “persona rosters” that rotate per stream segment
* Add vision-based cues into `StreamContext` (visual_summary)
* Add ephemeral memory cache for short-lived waves (“KEKW spam for 10s”)

---

## Appendix A: Worker internal flow (detailed)

```mermaid
flowchart TB
  subgraph Inputs
    Ctx[stream.context]:::bus
    Fire[chat.firehose]:::bus
    Tr[chat.trends]:::bus
  end

  subgraph Agent["AgentWorker"]
    Buf[Buffers & derived signals]:::mod
    Dec[Decision policy\np_post computation]:::mod
    MemR[Mem0 search\n(top-K)]:::mod
    Gen[LLM generation\n(one line)]:::mod
    Gate[Pre-send safety\n+ sanitize]:::mod
    Pub[Publish chat.ingest]:::mod
    Ext[Extraction prompt\n(JSON deltas)]:::mod
    MemW[Mem0 add\n(durable only)]:::mod
    Ref[Reflection loop\n(drift update)]:::mod
  end

  Ctx --> Buf
  Fire --> Buf
  Tr --> Buf

  Buf --> Dec --> MemR --> Gen --> Gate --> Pub
  Gen --> Ext --> MemW
  Ref --> MemW

  classDef bus fill:#efe,stroke:#464,stroke-width:1px;
  classDef mod fill:#eef,stroke:#446,stroke-width:1px;
```
