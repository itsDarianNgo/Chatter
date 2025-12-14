# Prompts

Prompt templates for personas and memory flows. Each prompt is referenced by `prompts/manifest.json`, which records ids, purposes, versions, paths, and sha256 digests. Use the manifest with `scripts/validate_llm_artifacts.py` to ensure files are present and unchanged.

SHA digests are computed on a canonical form to avoid CRLF/LF drift: prompts are read as UTF-8, newlines are normalized to `\n`, trailing newlines are trimmed, and exactly one newline is re-appended before hashing.

When running the LiteLLM or stub generation modes, the manifest drives which prompt file is used for persona replies. Update the manifest and recompute hashes if new prompt files are added.
