# memory_runtime

Deterministic memory runtime utilities for validating and exercising memory contracts without a live backend. This package ships:

- Shared types for memory items and query results
- A `MemoryStore` interface with an in-memory `StubMemoryStore` backed by JSON fixtures
- Policy helpers to load and evaluate memory policies
- Redaction utilities for conservative masking
- Schema validators for memory items and stub fixtures

The goal is to support CI/local testing with predictable data while keeping integration points ready for future backends.
