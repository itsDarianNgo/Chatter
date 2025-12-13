# safety

Shared safety utilities used across services.

## Responsibilities
- blocklist matching (config-driven)
- doxxing pattern detection + redaction
- link normalization and risky-content warnings
- shared “minimum policy” for bot outputs

Used by:
- gateway (final enforcement before broadcast)
- persona workers (pre-send gating)
- UI (defensive rendering)
