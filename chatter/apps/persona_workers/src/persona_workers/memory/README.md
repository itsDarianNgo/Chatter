# persona_workers/memory

Mem0 integration and memory hygiene.

## Responsibilities
- Provide a `MemoryAdapter` used by agents
- Enforce scoping conventions (recommended):
    - `mem0_user_id = "room:{room_id}|agent:{agent_name}"`
    - store other entities in metadata (e.g., `other_user`, `type`)
- Store durable signals, not raw spam:
    - relationships (affinity/rivalry/respect)
    - catchphrases/running jokes
    - preferences (topics, games, habits)
    - lore events (how a meme started)
    - persona drift snapshots

## Anti-noise rules
- Prefer storing extracted structured updates rather than full chat text
- Mark confidence where relevant (e.g., rumor vs confirmed)
