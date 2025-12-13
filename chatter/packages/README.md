# packages

Shared libraries and contracts used across apps.

## Goals
- one source of truth for message schemas (`protocol/`)
- shared safety filters and redaction utilities (`safety/`)
- shared observability setup (`observability/`)
- developer tooling (`devtools/`)

Apps should depend on packages rather than re-implementing common logic.
