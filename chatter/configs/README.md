# configs

Repository-tracked configuration used by services.

## Contents
- personas: roster definitions and persona constraints
- rooms: per-channel configuration (feature flags, multipliers)
- moderation: blocklists and redaction rules
- prompts: shared prompt fragments and policies

Services should load configs from here (or mounted equivalents in deployment).
