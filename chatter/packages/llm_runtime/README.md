# llm_runtime

Interfaces and validation helpers for deterministic LLM behavior in CI. Milestone 3A introduces a stub provider plus prompt and memory artifacts that can be validated without reaching external models.

## Components
- `LLMProvider` protocol and request/response types
- `StubLLMProvider` for fixture-driven deterministic replies
- Loaders and validators for provider config, memory policy, prompt manifests, and stub fixtures

## Fixture key strategy
The stub provider can key responses by `persona_id` and marker prefix (e.g., `ClipGoblin::E2E_TEST_`). When a marker is present in the request, the provider reduces it to a stable prefix and looks up a matching case, falling back to persona defaults and the configured default response.

## Prompt manifest validation
Use `prompt_loader` to load and verify the manifest, ensure prompt files exist, and enforce sha256 digests so accidental edits are detected.
