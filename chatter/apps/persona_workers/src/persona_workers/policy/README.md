# persona_workers/policy

Decision-making and safety gating for autonomous agents.

## Responsibilities
- Posting probability (“spam physics”):
    - baseline talkativeness
    - boosts from stream events
    - boosts from mentions/replies
    - optional boosts from trends (velocity/emote waves)
- Anti-loop dampening:
    - downweight bot-origin messages
    - avoid reacting to other bots repeatedly
- Output safety checks:
    - blocklisted content
    - doxxing patterns
    - harassment heuristics

Policy should be configurable per room and per persona.
