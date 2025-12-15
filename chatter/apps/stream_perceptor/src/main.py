from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from packages.llm_runtime.src import LLMRequest, PromptRenderer, StubLLMProvider, load_llm_provider_config

from .settings import settings
from .validator import JSONSchemaValidator

logging.basicConfig(level=settings.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="stream_perceptor")


def _parse_ts_ms(value: object) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:  # noqa: BLE001
            return None
    return None


def _resolve_frame_path(frame_path: str, repo_root: Path) -> Path:
    raw = (frame_path or "").strip()
    if not raw:
        return repo_root

    if raw.startswith("/app/"):
        rel = PurePosixPath(raw).relative_to("/app")
        return repo_root / Path(rel.as_posix())

    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate

    return repo_root / Path(PurePosixPath(raw).as_posix())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_prompt_entry(manifest: dict, prompt_id: str) -> dict:
    for entry in manifest.get("prompts", []):
        if entry.get("id") == prompt_id:
            return entry
    raise ValueError(f"prompt_id not found in manifest: {prompt_id}")


def _build_llm_provider(repo_root: Path, provider_config_path: str):
    provider_path = repo_root / provider_config_path
    provider_config = load_llm_provider_config(provider_path)
    provider_type = provider_config.get("provider")

    if provider_type == "stub":
        stub_cfg = provider_config.get("stub", {})
        fixtures_path = repo_root / stub_cfg.get("fixtures_path", "")
        provider = StubLLMProvider(
            fixtures_path=fixtures_path,
            default_response=stub_cfg.get("default_response", "ok"),
            key_strategy=stub_cfg.get("key_strategy", "persona_marker"),
            max_output_chars=int(provider_config.get("max_output_chars", 200)),
            provider_name="stub",
        )
        model = "stub"
    elif provider_type == "litellm":
        from packages.llm_runtime.src.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(provider_config)
        model = provider_config.get("litellm", {}).get("model") or "unknown"
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")

    return provider, provider_config, provider_type, model


@dataclass
class Stats:
    processed_frames: int = 0
    processed_transcripts: int = 0
    emitted_observations: int = 0
    llm_calls: int = 0
    llm_failures: int = 0
    schema_failures: int = 0
    sha_mismatch: int = 0
    file_missing: int = 0
    redis_failures: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "processed_frames": self.processed_frames,
            "processed_transcripts": self.processed_transcripts,
            "emitted_observations": self.emitted_observations,
            "llm_calls": self.llm_calls,
            "llm_failures": self.llm_failures,
            "schema_failures": self.schema_failures,
            "sha_mismatch": self.sha_mismatch,
            "file_missing": self.file_missing,
            "redis_failures": self.redis_failures,
        }


class StreamPerceptor:
    def __init__(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.stats = Stats()
        self.client: Optional[redis.Redis] = None
        self._stop = asyncio.Event()

        self.frame_validator = JSONSchemaValidator(self.repo_root / settings.schema_stream_frame_path)
        self.transcript_validator = JSONSchemaValidator(self.repo_root / settings.schema_stream_transcript_segment_path)
        self.observation_validator = JSONSchemaValidator(self.repo_root / settings.schema_stream_observation_path)

        self.provider, self.provider_cfg, self.provider_type, self.provider_model = _build_llm_provider(
            self.repo_root, settings.llm_provider_config_path
        )
        self.renderer = PromptRenderer(self.repo_root / settings.prompt_manifest_path, base_dir=self.repo_root)
        self.prompt_entry = _load_prompt_entry(self.renderer.manifest, "stream_observation_v1")

        self._watermark_ms: dict[str, int] = {}
        self._transcripts: dict[str, list[dict]] = {}

    async def connect(self) -> None:
        self.client = redis.from_url(settings.redis_url, decode_responses=True)
        await self._ensure_group(settings.stream_frames_key)
        await self._ensure_group(settings.stream_transcripts_key)
        logger.info("Connected to Redis at %s", settings.redis_url)

    async def _ensure_group(self, stream: str) -> None:
        assert self.client is not None
        try:
            await self.client.xgroup_create(stream, settings.consumer_group, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", settings.consumer_group, stream)
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return
            raise

    async def stop(self) -> None:
        self._stop.set()
        if self.client:
            await self.client.close()

    def _prune_transcripts(self, room_id: str) -> None:
        watermark = self._watermark_ms.get(room_id)
        if watermark is None:
            return
        cutoff = watermark - settings.transcript_buffer_retention_ms
        buf = self._transcripts.get(room_id) or []
        if not buf:
            return
        kept = [seg for seg in buf if int(seg.get("_ts_ms", 0)) >= cutoff]
        self._transcripts[room_id] = kept

    def _record_transcript(self, payload: dict) -> None:
        room_id = payload.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return
        ts_ms = _parse_ts_ms(payload.get("ts")) or 0
        self._watermark_ms[room_id] = max(self._watermark_ms.get(room_id, ts_ms), ts_ms)

        buf = self._transcripts.setdefault(room_id, [])
        enriched = dict(payload)
        enriched["_ts_ms"] = ts_ms
        buf.append(enriched)
        buf.sort(key=lambda seg: (int(seg.get("_ts_ms", 0)), str(seg.get("id", ""))))
        self._prune_transcripts(room_id)

    def _join_transcripts(self, room_id: str, frame_ts_ms: int) -> list[dict]:
        buf = self._transcripts.get(room_id) or []
        joined = []
        window = settings.transcript_join_window_ms
        for seg in buf:
            seg_ts = int(seg.get("_ts_ms", 0))
            if abs(seg_ts - frame_ts_ms) <= window:
                joined.append({k: v for k, v in seg.items() if k != "_ts_ms"})
        joined.sort(key=lambda seg: (_parse_ts_ms(seg.get("ts")) or 0, str(seg.get("id", ""))))
        return joined

    async def run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                if not self.client:
                    await self.connect()
                await self._consume_loop()
            except (RedisConnectionError, ConnectionError) as exc:
                self.stats.redis_failures += 1
                logger.warning("Redis connection lost (%s); retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                self.client = None
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in stream_perceptor loop: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _consume_loop(self) -> None:
        assert self.client is not None
        streams = {settings.stream_transcripts_key: ">", settings.stream_frames_key: ">"}
        while not self._stop.is_set():
            records = await self.client.xreadgroup(
                groupname=settings.consumer_group,
                consumername=settings.consumer_name,
                streams=streams,
                count=50,
                block=1000,
            )
            if not records:
                continue
            for stream_name, messages in records:
                for message_id, fields in messages:
                    await self._handle_message(stream_name, message_id, fields)

    async def _handle_message(self, stream_name: str, message_id: str, fields: Dict[str, Any]) -> None:
        assert self.client is not None
        raw = fields.get("data")
        schema_name: str | None = None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not isinstance(raw, str):
                raise ValueError("missing data field")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload must be object")

            schema_name = payload.get("schema_name") if isinstance(payload.get("schema_name"), str) else None
            if stream_name == settings.stream_transcripts_key:
                self.stats.processed_transcripts += 1
                self.transcript_validator.validate(payload)
                self._record_transcript(payload)
            elif stream_name == settings.stream_frames_key:
                self.stats.processed_frames += 1
                self.frame_validator.validate(payload)
                await self._process_frame(payload)
            else:
                logger.warning("Unknown stream %s; dropping message %s", stream_name, message_id)
        except Exception as exc:  # noqa: BLE001
            self.stats.schema_failures += 1
            logger.warning("Failed to process %s message %s (%s): %s", stream_name, message_id, schema_name, exc)
        finally:
            try:
                await self.client.xack(stream_name, settings.consumer_group, message_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to ack %s %s: %s", stream_name, message_id, exc)

    async def _process_frame(self, frame: dict) -> None:
        assert self.client is not None
        room_id = frame.get("room_id")
        if not isinstance(room_id, str) or not room_id:
            return
        ts_ms = _parse_ts_ms(frame.get("ts")) or 0
        self._watermark_ms[room_id] = max(self._watermark_ms.get(room_id, ts_ms), ts_ms)
        self._prune_transcripts(room_id)

        frame_path = frame.get("frame_path")
        if not isinstance(frame_path, str) or not frame_path.strip():
            self.stats.schema_failures += 1
            return
        resolved = _resolve_frame_path(frame_path, self.repo_root)
        if not resolved.exists():
            self.stats.file_missing += 1
            return

        expected_sha = frame.get("sha256")
        if not isinstance(expected_sha, str) or not expected_sha:
            self.stats.schema_failures += 1
            return

        actual_sha = _sha256_file(resolved)
        if actual_sha.lower() != expected_sha.lower():
            self.stats.sha_mismatch += 1
            return

        transcripts = self._join_transcripts(room_id, ts_ms)
        combined_text = " ".join(
            [seg.get("text", "") for seg in transcripts if isinstance(seg.get("text"), str)]
        ).strip()

        trace_template = {
            "provider": "stub" if self.provider_type == "stub" else str(self.provider_type),
            "model": str(self.provider_model),
            "latency_ms": 1 if self.provider_type == "stub" else 0,
            "prompt_id": self.prompt_entry.get("id"),
            "prompt_sha256": self.prompt_entry.get("sha256"),
        }
        payload = {
            "prompt_id": self.prompt_entry.get("id"),
            "prompt_sha256": self.prompt_entry.get("sha256"),
            "trace_template": trace_template,
            "frame": frame,
            "transcripts": transcripts,
        }

        req = LLMRequest(
            persona_id="stream_perceptor",
            persona_display_name="stream_perceptor",
            room_id=room_id,
            content=combined_text,
            marker=None,
            recent_messages=[],
            tags={},
        )
        system_prompt, user_prompt = self.renderer.render_stream_observation(payload)
        req.system_prompt = system_prompt
        req.user_prompt = user_prompt

        self.stats.llm_calls += 1
        try:
            t0 = time.time()
            response = self.provider.generate(req)
            elapsed_ms = int((time.time() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            self.stats.llm_failures += 1
            logger.warning("LLM call failed: %s", exc)
            return

        try:
            observation = json.loads(response.text or "")
            if not isinstance(observation, dict):
                raise ValueError("observation must be object")

            if self.provider_type != "stub":
                trace_val = observation.get("trace")
                if not isinstance(trace_val, dict):
                    raise ValueError("observation.trace must be object")
                trace_val["provider"] = str(self.provider_type)
                trace_val["model"] = str(self.provider_model)
                trace_val["latency_ms"] = elapsed_ms
                trace_val["prompt_id"] = self.prompt_entry.get("id")
                trace_val["prompt_sha256"] = self.prompt_entry.get("sha256")

            if observation.get("room_id") != room_id:
                raise ValueError("observation.room_id mismatch")
            if observation.get("frame_id") != frame.get("id"):
                raise ValueError("observation.frame_id mismatch")
            if str(observation.get("frame_sha256", "")).lower() != expected_sha.lower():
                raise ValueError("observation.frame_sha256 mismatch")
            expected_transcript_ids = [seg.get("id") for seg in transcripts if isinstance(seg.get("id"), str)]
            if observation.get("transcript_ids") != expected_transcript_ids:
                raise ValueError("observation.transcript_ids mismatch")

            self.observation_validator.validate(observation)
        except Exception as exc:  # noqa: BLE001
            self.stats.schema_failures += 1
            logger.warning("Invalid observation output: %s", exc)
            return

        await self.client.xadd(settings.stream_observations_key, {"data": json.dumps(observation, ensure_ascii=False)})
        self.stats.emitted_observations += 1


service = StreamPerceptor()


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(service.run())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await service.stop()


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/stats")
async def stats() -> dict[str, int]:
    return service.stats.as_dict()


if __name__ == "__main__":
    uvicorn.run("apps.stream_perceptor.src.main:app", host="0.0.0.0", port=settings.http_port, reload=False)
