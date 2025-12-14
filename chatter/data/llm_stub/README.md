# LLM Stub Fixtures

Deterministic fixtures for the stub LLM provider. Each case maps a lookup key to a single-line response, allowing tests to verify prompt plumbing without external API calls.

- Strategy `persona_marker` expects keys like `PersonaId::E2E_TEST_`.
- Update `data/llm_stub/fixtures/demo.json` to expand coverage; validate with `python scripts/validate_llm_artifacts.py`.
