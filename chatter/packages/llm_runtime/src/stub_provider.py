from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from .provider_base import LLMProvider
from .types import LLMRequest, LLMResponse


def _load_fixtures(path: Path) -> Dict[str, str]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return {case["key"]: case["response"] for case in payload.get("cases", [])}


def _clean_text(text: str, max_chars: int) -> str:
    single_line = re.sub(r"\s+", " ", text.replace("\n", " ").replace("\r", " ")).strip()
    single_line = single_line.replace("@", "")
    if len(single_line) > max_chars:
        return single_line[: max_chars - 1] + "…"
    return single_line


def _marker_prefix(marker: str) -> str:
    tokens = ["E2E_TEST_BOTLOOP_", "E2E_TEST_POLICY_", "E2E_TEST_", "E2E_MARKER_"]
    for token in tokens:
        if token in marker:
            idx = marker.find(token)
            return marker[idx : idx + len(token) + 12]
    return marker[:16]


def _deterministic_index(seed: str, modulo: int) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % modulo


def _normalize_summary(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ").replace("\r", " ")).strip()
    if not cleaned:
        return ""
    return cleaned.replace("OBS:", "OBS")


def _extract_observation_summary(summary: str, context: str) -> str:
    if summary and summary.strip():
        return summary
    if not context:
        return ""
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if idx == 0 and len(lines) > 1:
            if "OBS:" not in line and "|" not in line and "tags=" not in line and "entities=" not in line and "hype=" not in line:
                continue
        candidate = line
        if candidate.lower().startswith("obs:"):
            candidate = candidate[4:].strip()
        parts = [part.strip() for part in candidate.split(" | ") if part.strip()]
        for part in parts:
            lower = part.lower()
            if lower.startswith(("tags=", "entities=", "hype=")):
                continue
            if re.match(r"^\d{4}-\d{2}-\d{2}t", lower):
                continue
            return part
    return ""


def _extract_e2e_token(text: str) -> str:
    for token in ("E2E_REACTIVITY_OBS", "E2E_AUTO_OBS"):
        if token in text:
            return token
    for token in ("E2E_TEST_BOTLOOP_", "E2E_TEST_POLICY_", "E2E_TEST_", "E2E_MARKER_"):
        if token in text:
            idx = text.find(token)
            return text[idx : idx + len(token) + 12]
    return ""


def _build_chatty_stub_reply(req: LLMRequest, prompt_id: str, max_chars: int) -> str:
    summary_raw = _extract_observation_summary(req.observation_summary or "", req.observation_context or "")
    summary = _normalize_summary(summary_raw)
    token = _extract_e2e_token(summary)
    if not token and req.marker:
        token = _marker_prefix(req.marker)
    rest = summary.replace(token, "").strip(" :-,") if token else summary
    if not rest:
        rest = "wild"
    core = " ".join(part for part in (rest, token) if part).strip()
    seed = f"{req.persona_id}:{prompt_id}:{token}:{rest}"
    if prompt_id == "persona_chat_reply_v2":
        suffixes = ["lol", "yo", "sheesh", "lfg", "no shot"]
        suffix = suffixes[_deterministic_index(seed, len(suffixes))]
        reply = f"{core} {suffix}".strip()
    else:
        prefixes = ["sheesh", "yo", "no way", "lmao", "wtf"]
        prefix = prefixes[_deterministic_index(seed, len(prefixes))]
        reply = f"{prefix} {core}".strip()
    return _clean_text(reply, max_chars)


def _is_memory_extract(req: LLMRequest) -> bool:
    haystack = "\n".join([req.system_prompt or "", req.user_prompt or ""])
    return "MEMORY EXTRACTION REQUEST" in haystack


def _is_stream_observation(req: LLMRequest) -> bool:
    haystack = "\n".join([req.system_prompt or "", req.user_prompt or ""])
    return "STREAM OBSERVATION REQUEST" in haystack


def _build_memory_extract_response(req: LLMRequest) -> str:
    content = req.content or ""
    match = re.search(r"streamer is called\s+([A-Za-z0-9_()\-]+)", content, flags=re.IGNORECASE)
    value = match.group(1) if match else "Captain"
    item = {
        "schema_name": "MemoryItem",
        "schema_version": "1.0.0",
        "id": "memory_stub_streamer",
        "ts": "2024-01-01T00:00:00Z",
        "category": "room_lore",
        "subject": "streamer_name",
        "value": value,
        "confidence": 0.9,
        "ttl_days": 14,
        "source": {"kind": "chat_message", "message_id": None, "user_id": None, "origin": "human"},
    }
    return json.dumps([item], ensure_ascii=False)


def _extract_payload_json(user_prompt: str) -> Dict | None:
    marker = "PAYLOAD_JSON:"
    if marker not in (user_prompt or ""):
        return None
    raw = user_prompt.split(marker, 1)[1].strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _iso_from_epoch_ms(value: int) -> str:
    dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _build_stream_observation_response(req: LLMRequest) -> str:
    payload = _extract_payload_json(req.user_prompt or "") or {}
    frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else {}
    transcripts = payload.get("transcripts") if isinstance(payload.get("transcripts"), list) else []
    prompt_id = payload.get("prompt_id") if isinstance(payload.get("prompt_id"), str) else "stream_observation_v1"
    prompt_sha256 = payload.get("prompt_sha256") if isinstance(payload.get("prompt_sha256"), str) else ""

    trace_template = payload.get("trace_template")
    trace: dict = dict(trace_template) if isinstance(trace_template, dict) else {}
    trace.setdefault("provider", "stub")
    trace.setdefault("model", "stub")
    trace.setdefault("latency_ms", 1)
    trace.setdefault("prompt_id", prompt_id)
    trace.setdefault("prompt_sha256", prompt_sha256)

    frame_id = frame.get("id") if isinstance(frame.get("id"), str) else "frame"
    room_id = frame.get("room_id") if isinstance(frame.get("room_id"), str) else (req.room_id or "room:demo")
    ts_value = frame.get("ts")
    if isinstance(ts_value, int):
        ts = _iso_from_epoch_ms(ts_value)
    elif isinstance(ts_value, str):
        ts = ts_value
    else:
        ts = "2024-01-01T00:00:00Z"

    frame_sha = frame.get("sha256") if isinstance(frame.get("sha256"), str) else ""

    ordered_segments: list[dict] = []
    for seg in transcripts:
        if isinstance(seg, dict):
            ordered_segments.append(seg)

    transcript_ids: list[str] = []
    transcript_texts: list[str] = []
    for seg in ordered_segments:
        seg_id = seg.get("id")
        if isinstance(seg_id, str) and seg_id:
            transcript_ids.append(seg_id)
        text = seg.get("text")
        if isinstance(text, str) and text.strip():
            transcript_texts.append(text.strip())

    combined_text = " ".join(transcript_texts).strip()
    if not combined_text:
        combined_text = (req.content or "").strip()

    safe_summary = re.sub(r"\s+", " ", combined_text.replace("\n", " ").replace("\r", " ")).strip()
    if len(safe_summary) > 512:
        safe_summary = safe_summary[:511] + "."

    mentions = re.findall(r"@([A-Za-z0-9_]{1,64})", combined_text)
    entities: list[str] = []
    for mention in mentions:
        if mention and mention not in entities:
            entities.append(mention)

    exclamations = combined_text.count("!")
    hype_level = min(1.0, round(exclamations / 5.0, 2))

    tags: list[str] = []
    if "E2E_TEST_STREAM" in combined_text:
        tags.append("e2e")
    if "dragon" in combined_text.lower():
        tags.append("dragon")
    if exclamations > 0:
        tags.append("hype")
    if entities:
        tags.append("mentions")

    obs_seed = f"{frame_id}:{','.join(transcript_ids)}"
    obs_id = "obs_" + hashlib.sha256(obs_seed.encode("utf-8")).hexdigest()[:16]

    observation = {
        "schema_name": "StreamObservation",
        "schema_version": "1.0.0",
        "id": obs_id,
        "ts": ts,
        "room_id": room_id,
        "frame_id": frame_id,
        "frame_sha256": frame_sha,
        "transcript_ids": transcript_ids,
        "summary": safe_summary or "(no transcript)",
        "tags": tags,
        "entities": entities,
        "hype_level": hype_level,
        "safety": {
            "sexual_content": False,
            "violence": False,
            "self_harm": False,
            "hate": False,
            "harassment": False,
        },
        "trace": trace,
    }
    return json.dumps(observation, ensure_ascii=False, separators=(",", ":"))


class StubLLMProvider(LLMProvider):
    def __init__(
        self,
        fixtures_path: Path,
        default_response: str,
        key_strategy: str = "persona_marker",
        max_output_chars: int = 200,
        provider_name: str = "stub",
    ) -> None:
        self.fixtures_path = fixtures_path
        self.default_response = default_response
        self.key_strategy = key_strategy
        self.max_output_chars = max_output_chars
        self.provider_name = provider_name
        self.fixtures = _load_fixtures(fixtures_path)

    def _persona_marker_key(self, req: LLMRequest) -> str:
        prefix = _marker_prefix(req.marker) if req.marker else ""
        base_key = f"{req.persona_id}::{prefix}" if prefix else f"{req.persona_id}::DEFAULT"
        if prefix and base_key in self.fixtures:
            return base_key
        if prefix:
            candidate = f"{req.persona_id}::E2E_TEST_"
            if candidate in self.fixtures and prefix.startswith("E2E_TEST_"):
                return candidate
        return f"{req.persona_id}::DEFAULT"

    def _marker_only_key(self, req: LLMRequest) -> str:
        prefix = _marker_prefix(req.marker) if req.marker else ""
        return prefix or "DEFAULT"

    def _resolve_key(self, req: LLMRequest) -> str:
        if self.key_strategy == "marker_only":
            return self._marker_only_key(req)
        return self._persona_marker_key(req)

    def _lookup_response(self, key: str) -> str:
        if key in self.fixtures:
            return self.fixtures[key]
        return self.default_response

    def generate(self, req: LLMRequest) -> LLMResponse:
        if _is_stream_observation(req):
            text = _build_stream_observation_response(req)
            return LLMResponse(text=text, provider=self.provider_name, model="stub", meta={"mode": "stream_observation"})

        if _is_memory_extract(req):
            text = _build_memory_extract_response(req)
            return LLMResponse(text=text, provider=self.provider_name, model="stub", meta={"mode": "memory_extract"})

        prompt_id = req.prompt_id or ""
        if prompt_id in {"persona_chat_reply_v2", "persona_auto_commentary_v1"}:
            text = _build_chatty_stub_reply(req, prompt_id, self.max_output_chars)
            return LLMResponse(
                text=text, provider=self.provider_name, model="stub", meta={"mode": "chatty_stub", "prompt_id": prompt_id}
            )

        key = self._resolve_key(req)
        raw = self._lookup_response(key)
        text = _clean_text(raw, self.max_output_chars)
        return LLMResponse(text=text, provider=self.provider_name, model=None, meta={"key": key})
