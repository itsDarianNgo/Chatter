# Definition of Done Checklist

This checklist defines “done” for each milestone in the `chatter` roadmap. The goal is to keep quality consistent, reduce rework, and ensure every step is shippable.

Related:
- `docs/architecture/system_overview.md`
- `docs/architecture/protocols.md`
- `docs/architecture/persona_workers_spec.md`
- `docs/architecture/build_roadmap.md` (or equivalent roadmap doc)

---

## Global DoD (applies to every milestone)

### Contracts & compatibility
- [ ] All produced/consumed messages validate against `packages/protocol/` schemas.
- [ ] `schema_name` and `schema_version` are present on every message.
- [ ] Unknown fields are ignored safely by consumers.
- [ ] Breaking schema changes (field removals/type changes) are not introduced without a major bump + migration notes.

### Safety (defense in depth)
- [ ] Persona workers run pre-send checks (one-line, max length, basic blocklist/PII patterns).
- [ ] Chat gateway performs final safety enforcement before broadcast.
- [ ] Web UI renders defensively (no unsafe HTML, safe link handling).

### Observability
- [ ] Structured logging includes at minimum: `service`, `room_id`, and (if applicable) `agent_id`.
- [ ] Key errors are counted and surfaced (LLM failures, Mem0 failures, bus reconnects).
- [ ] Latency measurements exist for the critical path (ingest → broadcast, generation time).

### Performance / stability
- [ ] System remains stable under a defined load test for the milestone (document the target).
- [ ] Backpressure behavior is defined (batching/dropping policy) or explicitly out of scope.

### Documentation
- [ ] Any new module or interface has a short doc update explaining what changed.
- [ ] Configuration keys added in code are documented in the relevant `configs/` README (later) and/or architecture docs.

---

## Milestone 0 — Repo & contracts (foundation) DoD

### Folder structure and docs
- [ ] Repo directory structure exists as defined.
- [ ] `docs/architecture/system_overview.md` exists.
- [ ] `docs/architecture/protocols.md` exists.
- [ ] `docs/architecture/persona_workers_spec.md` exists.
- [ ] `docs/architecture/build_roadmap.md` exists (or equivalent).

### Protocol schemas
- [ ] JSON Schema drafts exist for `StreamContext`, `ChatMessage`, `TrendsSnapshot` in `packages/protocol/jsonschema/`.
- [ ] Each schema has at least one example JSON instance (valid) checked in under `packages/protocol/` or `data/schemas/`.
- [ ] A versioning policy is documented (SemVer-ish) and referenced by all services.

### Config stubs
- [ ] `configs/personas/` contains at least 2 persona examples (anchors + drift bounds).
- [ ] `configs/moderation/` contains a placeholder policy (blocklist/PII patterns).
- [ ] `configs/rooms/` contains at least one room example with tuning knobs.

---

## Milestone 1 — Vertical slice (fake messages → gateway → UI) DoD

### Chat gateway
- [ ] Can accept/consume `chat.ingest` and broadcast to WebSocket clients.
- [ ] Publishes everything broadcast to `chat.firehose`.
- [ ] Validates inbound `ChatMessage` and drops invalid payloads with telemetry.
- [ ] Basic safety stub exists (at least: max length + newline stripping + basic blocklist hooks).

### Web UI
- [ ] Connects to gateway WebSocket; reconnects on failure.
- [ ] Renders a high-throughput message list without crashing (virtualized or buffered).
- [ ] Displays `display_name`, badges, and basic styling.

### Smoke test
- [ ] A stub publisher can post 1000 messages and UI remains responsive.
- [ ] Gateway logs show broadcast rates; no unhandled exceptions.

---

## Milestone 2 — Persona Workers MVP (stub context, minimal memory) DoD

### Worker core
- [ ] Loads persona roster from `configs/personas/`.
- [ ] Subscribes to `stream.context` (even if stubbed).
- [ ] Independently posts based on policy (no orchestrator logic).
- [ ] Produces valid `ChatMessage` on `chat.ingest` with `origin="bot"`.
- [ ] Enforces “one line only” and max chars before publish.

### LLM integration
- [ ] LLM calls are concurrency-limited per process.
- [ ] Timeouts and retries/backoff exist (or clear failure behavior documented).
- [ ] Agent generation produces one message only (no explanations).

### Minimal Mem0
- [ ] Mem0 connectivity works end-to-end.
- [ ] Workers can do a basic `search` and `add` in their persona scope.
- [ ] If Mem0 fails, workers degrade gracefully (no crash).

### Load check
- [ ] With 10–50 agents, system stays stable for 10 minutes.
- [ ] Worker CPU/memory stays within expected bounds (document rough numbers).

---

## Milestone 3 — Real stream context (audio transcript first) DoD

### Stream context service
- [ ] Ingests live audio input and publishes `StreamContext` on cadence.
- [ ] Provides `summary` + `keywords` consistently (bounded length).
- [ ] Produces `transcript_window` with reasonable segmentation.

### Integration
- [ ] Persona workers react to live audio (visible relevance).
- [ ] End-to-end latency from speech → bot reaction is measured and acceptable (target documented).

### Stability
- [ ] Service tolerates ASR gaps and continues publishing.
- [ ] No schema drift or oversized payloads.

---

## Milestone 4 — Memory hygiene + durable extraction DoD

### Durable memory pipeline
- [ ] After sending a message, workers run extraction that outputs JSON-only.
- [ ] Only extracted, structured deltas are written to Mem0 (not raw spam).
- [ ] Memory items include required metadata (`type`, `confidence`, optional `other_user`).

### Scoping
- [ ] Mem0 scoping convention is enforced:
    - `mem0_user_id = "room:{room_id}|agent:{agent_name}"` (recommended)
- [ ] Retrieval queries reliably return persona-specific memories.

### Quality checks
- [ ] After 30 minutes of spam, memory contains coherent:
    - at least one running joke
    - at least one preference
    - at least one relationship note (when interactions exist)
- [ ] “False facts” are minimized via confidence tagging and hygiene rules.

---

## Milestone 5 — Persona drift/reflection loop DoD

### Drift behavior
- [ ] Reflection runs at configured interval or message count.
- [ ] Drift updates are bounded by per-persona constraints (min/max and step caps).
- [ ] Drift snapshots are persisted (Mem0 or a dedicated store) and loaded on restart.

### Persona continuity
- [ ] Personas remain recognizable (voice rules hold) while evolving.
- [ ] Relationships and catchphrases persist across restarts/sessions.
- [ ] Drift does not oscillate wildly (documented tests / logs show stability).

---

## Milestone 6 — Trends and waves DoD (optional)

### Trends snapshot
- [ ] `TrendsSnapshot` is computed and published every 1–2 seconds.
- [ ] Includes msg velocity, top tokens/emotes, top mentions, bot_fraction.

### Agent usage
- [ ] Agents can join waves without becoming identical.
- [ ] Trend boosts are tuned per persona trait (meme_level etc.).
- [ ] Bot-only loops remain bounded (dampening still works).

---

## Milestone 7 — Safety hardening & ops readiness DoD

### Safety hardening
- [ ] Expanded blocklists and PII redaction patterns are active.
- [ ] Gateway produces `moderation` metadata for allow/redact/drop.
- [ ] Safety incidents are logged with reasons and counts.

### Ops readiness
- [ ] Minimal dashboards or logs exist to diagnose:
    - gateway lag
    - Mem0 latency spikes
    - LLM failure spikes
    - runaway posting rates
- [ ] Runbooks exist for top failure modes.
- [ ] Replay tooling can reproduce a session deterministically (at least for dev).

---

# Risk Register (Short)

This register lists likely risks and mitigations for `chatter` in early builds.

---

## R1 — Bot-only feedback loops (runaway spam)
**Impact:** Chat becomes a bot echo chamber; costs spike; UX degrades.  
**Likelihood:** High (if reading firehose).  
**Mitigations:**
- Human-first sampling (prefer `origin="human"`).
- Dampening based on `bot_fraction`.
- Only react to bot messages when directly mentioned/replied.
- Add emergency “room brake” multiplier to reduce `p_post`.

---

## R2 — Memory pollution (spam becomes “facts”)
**Impact:** Personas hallucinate persistent false lore; trust drops.  
**Likelihood:** High.  
**Mitigations:**
- Two-step memory writes: extraction JSON → durable store only.
- Confidence tagging; avoid storing speculation.
- Store preferences/relationships, not raw chat text.
- Periodic memory audits (devtools/replay) and pruning policies.

---

## R3 — Latency spikes (LLM or Mem0 slows the loop)
**Impact:** Delayed reactions; chat feels “off”; backlogs grow.  
**Likelihood:** Medium–High.  
**Mitigations:**
- Concurrency caps; timeouts and backoff.
- Thin retrieval (top-K small).
- Degrade gracefully: post without memory when Mem0 is slow.
- Optional queue depth awareness to reduce posting when saturated.

---

## R4 — Gateway overload (broadcast fanout under spam)
**Impact:** WebSocket disconnects; clients lag; messages drop.  
**Likelihood:** Medium.  
**Mitigations:**
- Batching broadcasts; drop oldest under overload (document behavior).
- Virtualized UI list + client-side buffering.
- Keep gateway “boring” (no LLM work).
- Add load testing early (Milestone 1/2).

---

## R5 — Schema drift and integration breakage
**Impact:** Services stop understanding each other; silent drops.  
**Likelihood:** Medium.  
**Mitigations:**
- Protocol-first changes; schema validation at boundaries.
- Contract tests in CI.
- SemVer discipline; migration notes for breaking changes.
- Strict logging when dropping invalid messages.

---

## R6 — Unsafe outputs (policy violations)
**Impact:** Reputation damage; platform issues; user harm.  
**Likelihood:** Medium.  
**Mitigations:**
- Defense in depth: worker pre-send + gateway final enforcement.
- Config-driven blocklists/PII redaction.
- Keep prompts explicit about disallowed categories.
- Telemetry for moderation actions; quick rollback knobs.

---

## R7 — Cost explosion (too many agents / too frequent LLM calls)
**Impact:** Runaway spend; throttling; system instability.  
**Likelihood:** High unless capped.  
**Mitigations:**
- Hard concurrency limits and budgets per room.
- Use short prompts and short outputs.
- Increase tick jitter and reduce baseline talkativeness.
- Add a “cost governor” (global multiplier) as a kill switch.

---

## R8 — Persona collapse (agents become same-y)
**Impact:** UX becomes boring; personas feel fake.  
**Likelihood:** Medium.  
**Mitigations:**
- Strong anchors (voice rules, quirks) separate from drift.
- Trait-driven trend participation (not everyone spams the same way).
- Retrieval that favors persona-specific memories.
- Diversity tests (measure lexical/style variance).

---

## R9 — Data handling/PII risk in logs/memory
**Impact:** Compliance/privacy issues; user risk.  
**Likelihood:** Medium.  
**Mitigations:**
- Redact PII before storing logs and before writing to memory.
- Avoid storing raw chat logs in memory; store summaries/deltas.
- Keep `trace` metadata minimal; no payload dumps by default.

---

## R10 — Debuggability gaps (can’t reproduce issues)
**Impact:** Slow iteration; recurring regressions.  
**Likelihood:** Medium.  
**Mitigations:**
- Save bounded “session traces” (context + firehose sample) for replay.
- Add replay tool early; deterministic fixtures.
- Structured logs with correlation IDs.

---
