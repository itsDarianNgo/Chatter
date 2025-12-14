import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from packages.memory_runtime.src import (
    Mem0Client,
    Mem0MemoryStore,
    MemoryItem,
    MemoryStore,
    StubMemoryStore,
    apply_redactions,
    load_memory_policy,
    should_store_item,
    validate_memory_item_dict,
)
from packages.memory_runtime.src.llm_extract import LLMMemoryExtractor
from packages.llm_runtime.src import LLMRequest, PromptRenderer

from .bus_redis_streams import ack, connect, ensure_consumer_group, read_messages
from .config_loader import ConfigLoader
from .generator import LLMReplyGenerator, build_llm_provider, build_reply_generator
from .policy import PolicyEngine, ts_ms_from_event
from .publisher import publish_chat_message
from .settings import settings
from .state import RuntimeState, Stats
from .validator import ChatMessageValidator

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="persona_workers")


class PersonaWorkerService:
    def __init__(self) -> None:
        base_path = Path(__file__).resolve().parents[3]
        self.validator = ChatMessageValidator(base_path / settings.schema_chat_message_path)
        self.config_loader = ConfigLoader(
            base_path=base_path,
            room_schema_path=base_path / settings.schema_room_path,
            persona_schema_path=base_path / settings.schema_persona_path,
        )
        self.room_config = self.config_loader.load_room_config(settings.room_config_path)
        enabled_personas = self.room_config.get("enabled_personas", [])
        self.personas = self.config_loader.load_persona_configs(settings.persona_config_dir, enabled_personas)
        self.state = RuntimeState(settings.max_recent_messages_per_room, settings.dedupe_cache_size)
        self.stats = Stats()
        self.base_path = base_path
        self.redis = None
        self._stop = asyncio.Event()
        self.budget_limit = int(
            self.room_config.get("timing", {}).get("max_bot_msgs_per_10s", settings.room_bot_budget_per_10s_default)
        )
        self.budget_window_ms = 10_000
        self.policy_engine = PolicyEngine(self.room_config, self.personas, self.state)
        self.reply_generator = build_reply_generator(
            base_path,
            settings.generation_mode,
            settings.llm_provider_config_path,
            settings.prompt_manifest_path,
        )
        self.memory_enabled = settings.memory_enabled
        self.memory_backend = None
        self.memory_policy = None
        self.memory_store: MemoryStore | None = None
        self.memory_policy_path: str | None = None
        self.memory_fixtures_path: str | None = None
        self.memory_max_items = settings.memory_max_items
        self.memory_max_chars = settings.memory_max_chars
        self.memory_extract_strategy = (settings.memory_extract_strategy or "heuristic").lower()
        self.memory_scope_user_enabled = settings.memory_scope_user_enabled
        self.memory_extractor: LLMMemoryExtractor | None = None
        self.memory_llm_renderer: PromptRenderer | None = None
        self.memory_llm_provider = None
        self.memory_llm_provider_config: dict | None = None
        self.memory_write_window_ms = 60_000
        self.memory_write_limit = 5
        self.memory_write_times: dict[str, deque[int]] = {}
        self._init_memory()
        self._init_memory_extractor()

    async def start(self) -> None:
        await self._connect()
        asyncio.create_task(self._run())

    def _init_memory(self) -> None:
        self.stats.memory_enabled = self.memory_enabled
        self.stats.memory_extract_strategy = self.memory_extract_strategy
        try:
            if not self.memory_enabled:
                return
            policy_path = self.base_path / settings.memory_policy_path
            self.memory_policy_path = str(policy_path)
            self.stats.memory_policy_path = self.memory_policy_path
            self.memory_policy = load_memory_policy(policy_path)

            backend = (settings.memory_backend or "stub").lower()
            self.memory_backend = backend
            self.stats.memory_backend = backend

            if backend == "stub":
                fixtures_path = self.base_path / settings.memory_fixtures_path
                self.memory_fixtures_path = str(fixtures_path)
                self.stats.memory_fixtures_path = self.memory_fixtures_path
                self.memory_store = StubMemoryStore(fixtures_path)
            elif backend == "mem0":
                self.stats.mem0_base_url = settings.mem0_base_url
                self.stats.mem0_org_configured = bool(settings.mem0_org_id)
                self.stats.mem0_project_configured = bool(settings.mem0_project_id)

                if not settings.mem0_api_key:
                    self.memory_enabled = False
                    self.stats.memory_enabled = False
                    self.stats.last_memory_error = "mem0_missing_api_key"
                    logger.warning("Mem0 backend requested but MEM0_API_KEY missing; disabling memory")
                    return

                client = Mem0Client(
                    api_key=settings.mem0_api_key,
                    base_url=settings.mem0_base_url,
                    timeout_s=settings.mem0_timeout_s,
                    org_id=settings.mem0_org_id or None,
                    project_id=settings.mem0_project_id or None,
                )
                self.memory_store = Mem0MemoryStore(
                    client, max_items=self.memory_max_items, max_chars=self.memory_max_chars
                )
            else:
                self.memory_enabled = False
                self.stats.memory_enabled = False
                self.stats.last_memory_error = f"unsupported_backend:{backend}"
                logger.warning("Memory backend %s not implemented; disabling memory", backend)
        except Exception as exc:  # noqa: BLE001
            self.memory_enabled = False
            self.stats.memory_enabled = False
            self.stats.last_memory_error = str(exc)[:200]
            logger.warning("Memory init failed: %s", exc)

    def _init_memory_extractor(self) -> None:
        self.stats.memory_llm_provider = None
        self.stats.memory_llm_model = None
        if not (self.memory_enabled and self.memory_policy):
            return
        if self.memory_extract_strategy != "llm":
            return

        try:
            renderer = None
            provider = None
            provider_cfg = None
            max_output_chars = self.memory_max_chars

            if isinstance(self.reply_generator, LLMReplyGenerator):
                renderer = self.reply_generator.renderer
                provider = self.reply_generator.provider
                provider_cfg = getattr(self.reply_generator, "provider_config", None)
                max_output_chars = getattr(self.reply_generator, "max_output_chars", self.memory_max_chars)

            if renderer is None or provider is None:
                provider, provider_cfg, max_output_chars = build_llm_provider(
                    self.base_path, self.base_path / settings.llm_provider_config_path
                )
                renderer = PromptRenderer(self.base_path / settings.prompt_manifest_path, base_dir=self.base_path)

            provider_type = (provider_cfg or {}).get("provider")
            model = None
            if provider_type == "litellm":
                model = (provider_cfg or {}).get("litellm", {}).get("model")
            elif provider_type == "stub":
                model = "stub"

            self.stats.memory_llm_provider = provider_type
            self.stats.memory_llm_model = model

            self.memory_llm_provider = provider
            self.memory_llm_renderer = renderer
            self.memory_llm_provider_config = provider_cfg or {}
            self.memory_extractor = LLMMemoryExtractor(
                provider=provider,
                renderer=renderer,
                policy=self.memory_policy or {},
                max_items=self.memory_max_items,
                max_chars=max_output_chars,
                scope_user_enabled=self.memory_scope_user_enabled,
            )
        except Exception as exc:  # noqa: BLE001
            self.stats.memory_extract_strategy = "heuristic"
            self.memory_extract_strategy = "heuristic"
            self.stats.last_memory_extract_error = str(exc)[:200]
            logger.warning("Memory LLM extractor init failed: %s", exc)

    async def shutdown(self) -> None:
        self._stop.set()
        if self.redis:
            await self.redis.close()

    async def _connect(self) -> None:
        backoff = 1
        while not self.redis:
            try:
                self.redis = await connect(settings.redis_url)
                await ensure_consumer_group(self.redis, settings.firehose_stream, settings.consumer_group)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis connection failed (%s); retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _record_memory_error(self, message: str) -> None:
        truncated = (message or "")[:200]
        self.stats.last_memory_error = truncated

    def _record_memory_extract_error(self, message: str) -> None:
        truncated = (message or "")[:200]
        self.stats.last_memory_extract_error = truncated

    def _memory_inventory(self) -> tuple[int, dict[str, int]]:
        if not self.memory_store:
            return 0, {}
        counts: dict[str, int] = {}
        total = 0
        for items in self.memory_store.dump().values():
            for item in items:
                total += 1
                counts[item.scope_key] = counts.get(item.scope_key, 0) + 1
        self.stats.memory_items_total = total
        self.stats.memory_items_by_scope = counts
        return total, counts

    def _memory_stats_payload(self) -> dict:
        total, counts = self._memory_inventory()
        return {
            "memory_enabled": self.memory_enabled,
            "memory_backend": self.memory_backend,
            "memory_policy_path": self.memory_policy_path,
            "memory_fixtures_path": self.memory_fixtures_path,
            "memory_items_total": total,
            "memory_items_by_scope": counts,
            "memory_reads_attempted": self.stats.memory_reads_attempted,
            "memory_reads_succeeded": self.stats.memory_reads_succeeded,
            "memory_reads_failed": self.stats.memory_reads_failed,
            "memory_writes_attempted": self.stats.memory_writes_attempted,
            "memory_writes_accepted": self.stats.memory_writes_accepted,
            "memory_writes_rejected": self.stats.memory_writes_rejected,
            "memory_writes_redacted": self.stats.memory_writes_redacted,
            "memory_writes_failed": self.stats.memory_writes_failed,
            "memory_extract_strategy": self.stats.memory_extract_strategy,
            "memory_llm_provider": self.stats.memory_llm_provider,
            "memory_llm_model": self.stats.memory_llm_model,
            "memory_extract_llm_attempted": self.stats.memory_extract_llm_attempted,
            "memory_extract_llm_succeeded": self.stats.memory_extract_llm_succeeded,
            "memory_extract_llm_failed": self.stats.memory_extract_llm_failed,
            "mem0_base_url": self.stats.mem0_base_url,
            "mem0_org_configured": self.stats.mem0_org_configured,
            "mem0_project_configured": self.stats.mem0_project_configured,
            "last_memory_read_ids": list(self.stats.last_memory_read_ids),
            "last_memory_write_ids": list(self.stats.last_memory_write_ids),
            "last_memory_extract_error": self.stats.last_memory_extract_error,
            "last_memory_error": self.stats.last_memory_error,
        }

    def _within_write_limit(self, room_id: str, now_ms: int) -> bool:
        window = self.memory_write_times.setdefault(room_id, deque())
        while window and now_ms - window[0] > self.memory_write_window_ms:
            window.popleft()
        return len(window) < self.memory_write_limit

    def _record_write_time(self, room_id: str, now_ms: int) -> None:
        window = self.memory_write_times.setdefault(room_id, deque())
        window.append(now_ms)

    def _derive_target_persona_id(self, content: str) -> str | None:
        enabled_personas = list(self.personas.keys())
        if not enabled_personas:
            self.stats.memory_writes_rejected += 1
            self._record_memory_error("memory_write_rejected:no_enabled_personas")
            return None

        lowered = (content or "").lower()
        for persona_id in enabled_personas:
            persona_lower = persona_id.lower()
            if f"@{persona_lower}" in lowered or persona_lower in lowered:
                return persona_id

        return enabled_personas[0]

    def _build_scope(self, scope_policy: dict, room_id: str, persona_id: str, user_id: str | None) -> tuple[str, str]:
        allowed_scopes = scope_policy.get("scopes") or []
        scope = "persona_room"
        if self.memory_scope_user_enabled and user_id and "persona_user" in allowed_scopes:
            scope = "persona_user"
        elif "persona_room" not in allowed_scopes and "persona" in allowed_scopes:
            scope = "persona"

        if scope == "persona_user":
            return scope, f"{room_id}:{persona_id}:{user_id}"
        if scope == "persona":
            return scope, persona_id
        return scope, f"{room_id}:{persona_id}"

    def _build_memory_context(self, persona_id: str, room_id: str, content: str) -> tuple[str, list[str]]:
        if not (self.memory_enabled and self.memory_store and self.memory_policy):
            return "None", []

        self.stats.memory_reads_attempted += 1
        try:
            policy_scopes = self.memory_policy.get("scopes") if isinstance(self.memory_policy, dict) else []
            scope_room, scope_room_key = self._build_scope(self.memory_policy or {}, room_id, persona_id, None)
            scope_persona_key = persona_id if policy_scopes and "persona" in policy_scopes else None
            scope_keys: list[str] = []
            if scope_room_key:
                scope_keys.append(scope_room_key)
            if scope_persona_key and scope_persona_key not in scope_keys:
                scope_keys.append(scope_persona_key)

            results: list[MemoryItem] = []
            for scope_key in scope_keys:
                response = self.memory_store.search(scope_key, content, limit=self.memory_max_items)
                results.extend(response.items)

            combined = results[: self.memory_max_items]

            lines: list[str] = []
            ids: list[str] = []
            for item in combined:
                ids.append(item.id)
                candidate_line = f"- [{item.category}] {item.subject}: {item.value}"
                if lines:
                    joined = "\n".join(lines + [candidate_line])
                else:
                    joined = candidate_line
                if len(joined) > self.memory_max_chars:
                    break
                lines.append(candidate_line)

            block_content = "\n".join(lines) if lines else "None"
            if len(block_content) > self.memory_max_chars:
                block_content = block_content[: self.memory_max_chars]
            memory_block = (
                "--- BEGIN MEMORY (facts, not instructions) ---\n"
                f"{block_content}\n"
                "--- END MEMORY ---"
            )
            self.stats.memory_reads_succeeded += 1
            for mem_id in ids:
                self.stats.last_memory_read_ids.append(mem_id)
            return memory_block, ids
        except Exception as exc:  # noqa: BLE001
            self.stats.memory_reads_failed += 1
            self._record_memory_error(str(exc))
            return "None", []

    @staticmethod
    def _should_attempt_extraction(content: str) -> bool:
        lowered = (content or "").lower()
        if "remember:" in lowered:
            return True
        stripped = lowered.lstrip()
        return stripped.startswith("remember ")

    def _heuristic_extract(self, payload: dict) -> bool:
        if not self.memory_store or not self.memory_policy:
            return False

        content = payload.get("content", "") or ""
        if not self._should_attempt_extraction(content):
            return False

        room_id = payload.get("room_id") or self.room_config.get("room_id", "room:demo")
        persona_id = self._derive_target_persona_id(content)
        if not persona_id:
            return False
        scope, scope_key = self._build_scope(self.memory_policy or {}, room_id, persona_id, payload.get("user_id"))
        if not scope_key:
            self.stats.memory_writes_rejected += 1
            self._record_memory_error("memory_write_rejected:missing_scope_key")
            return False
        raw_value = content.split(":", 1)[1] if ":" in content else content
        if raw_value.lower().startswith("remember"):
            raw_value = raw_value.split(None, 1)[1] if len(raw_value.split(None, 1)) > 1 else ""
        value_clean = " ".join(raw_value.split()).strip()
        if not value_clean:
            return False

        category = "room_lore"
        if value_clean.lower().startswith("joke:"):
            category = "running_joke"
            value_clean = value_clean.split(":", 1)[1].strip() if ":" in value_clean else value_clean

        ttl_default = self.memory_policy.get("ttl_days_default", 30)
        hashed = hashlib.sha256(f"{room_id}:{value_clean}".encode("utf-8")).hexdigest()[:16]
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        candidate = {
            "schema_name": "MemoryItem",
            "schema_version": "1.0.0",
            "id": hashed,
            "ts": now_ts,
            "scope": scope,
            "scope_key": scope_key,
            "category": category,
            "subject": "room",
            "value": value_clean,
            "confidence": 0.9,
            "ttl_days": ttl_default,
            "source": {
                "kind": "chat_message",
                "message_id": payload.get("id"),
                "user_id": payload.get("user_id"),
                "origin": payload.get("origin", "human"),
            },
        }

        redacted_value, notes = apply_redactions(candidate.get("value", ""), self.memory_policy)
        candidate["value"] = redacted_value
        if notes:
            candidate["redactions"] = notes
            self.stats.memory_writes_redacted += 1
        if not redacted_value or redacted_value.replace("[REDACTED]", "").strip() == "":
            self.stats.memory_writes_rejected += 1
            return False

        try:
            validate_memory_item_dict(candidate)
        except Exception as exc:  # noqa: BLE001
            self.stats.memory_writes_rejected += 1
            self._record_memory_error(str(exc))
            return False

        allowed, _ = should_store_item(self.memory_policy, candidate)
        if not allowed:
            self.stats.memory_writes_rejected += 1
            return False

        now_ms = int(time.time() * 1000)
        if not self._within_write_limit(room_id, now_ms):
            self.stats.memory_writes_rejected += 1
            return False

        try:
            memory_item = MemoryItem.from_dict(candidate)
            self.memory_store.upsert(scope_key, memory_item)
        except Exception as exc:  # noqa: BLE001
            self.stats.memory_writes_failed += 1
            self._record_memory_error(str(exc))
            return False

        self.stats.memory_writes_accepted += 1
        self.stats.last_memory_write_ids.append(candidate["id"])
        self._record_write_time(room_id, now_ms)
        return True

    def _llm_extract(self, payload: dict) -> bool:
        self.stats.memory_extract_llm_attempted += 1

        if not (self.memory_extractor and self.memory_store):
            self.stats.memory_extract_llm_failed += 1
            self._record_memory_extract_error("llm_extractor_unavailable")
            return False

        content = payload.get("content", "") or ""
        room_id = payload.get("room_id") or self.room_config.get("room_id", "room:demo")
        persona_id = self._derive_target_persona_id(content)
        if not persona_id:
            self.stats.memory_extract_llm_failed += 1
            self.stats.memory_writes_rejected += 1
            self._record_memory_extract_error("memory_llm_no_persona")
            return False
        room_state = self.state.get_room_state(room_id, self.budget_limit, self.budget_window_ms)
        recent_messages = [msg.get("content", "") or "" for msg in room_state.recent_messages]

        try:
            result = self.memory_extractor.extract(
                content=content,
                room_id=room_id,
                persona_id=persona_id,
                user_id=payload.get("user_id"),
                display_name=payload.get("display_name"),
                message_id=payload.get("id"),
                origin=payload.get("origin"),
                recent_messages=recent_messages,
            )
        except Exception as exc:  # noqa: BLE001
            self.stats.memory_extract_llm_failed += 1
            self._record_memory_extract_error(str(exc))
            return False

        if result.error:
            self._record_memory_extract_error(result.error)

        self.stats.memory_writes_rejected += result.rejected_count
        self.stats.memory_writes_redacted += result.redacted_count

        any_accepted = False
        for item in result.accepted_items:
            try:
                self.memory_store.upsert(item.scope_key, item)
                any_accepted = True
                self.stats.memory_writes_accepted += 1
                self.stats.last_memory_write_ids.append(item.id)
            except Exception as exc:  # noqa: BLE001
                self.stats.memory_writes_failed += 1
                self._record_memory_error(str(exc))

        if any_accepted:
            self.stats.memory_extract_llm_succeeded += 1
            self._record_write_time(room_id, int(time.time() * 1000))
            self.stats.last_memory_extract_error = None
        else:
            self.stats.memory_extract_llm_failed += 1

        return any_accepted

    def _maybe_extract_memory(self, payload: dict) -> None:
        if not (self.memory_enabled and self.memory_store and self.memory_policy):
            return

        origin = (payload.get("origin") or "").lower()
        if origin != "human":
            return

        moderation = payload.get("moderation") or {}
        action = moderation.get("action") if isinstance(moderation, dict) else None
        if action and str(action).lower() != "allow":
            return

        strategy = self.memory_extract_strategy
        if strategy == "off":
            return

        content = payload.get("content", "") or ""
        if not self._should_attempt_extraction(content):
            return

        self.stats.memory_writes_attempted += 1
        rejected_before = self.stats.memory_writes_rejected
        handled = False
        if strategy == "llm":
            handled = self._llm_extract(payload)
        if not handled:
            handled = self._heuristic_extract(payload)
        if not handled and self.stats.memory_writes_rejected == rejected_before:
            self.stats.memory_writes_rejected += 1

    async def _run(self) -> None:
        assert self.redis is not None
        while not self._stop.is_set():
            try:
                messages = await read_messages(
                    self.redis,
                    settings.firehose_stream,
                    settings.consumer_group,
                    settings.consumer_name,
                    count=20,
                    block_ms=1000,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Read loop error: %s", exc)
                await asyncio.sleep(1)
                continue
            if not messages:
                continue
            for redis_id, raw in messages:
                await self._handle_message(redis_id, raw)

    async def _handle_message(self, redis_id: str, raw_data: str) -> None:
        assert self.redis is not None
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON for %s", redis_id)
            await ack(self.redis, settings.firehose_stream, settings.consumer_group, redis_id)
            return

        try:
            self.stats.messages_consumed += 1
            if not isinstance(payload, dict):
                return

            message_id = payload.get("id")
            room_id = payload.get("room_id", "room:demo")
            if not message_id:
                return

            ts_ms = ts_ms_from_event(payload)

            if self.state.seen_before(message_id):
                self.stats.messages_deduped += 1
                self.stats.record_decision(persona_id="*", reason="deduped", tags={"ts_ms": ts_ms})
                return

            self.state.record_event(room_id, ts_ms, payload.get("origin", ""), self.budget_limit, self.budget_window_ms)

            self.validator.validate(payload)

            self.state.add_recent_message(room_id, payload, self.budget_limit, self.budget_window_ms)

            self._maybe_extract_memory(payload)

            for persona_id, persona in self.personas.items():
                decision, reason, tags = self.policy_engine.should_speak(persona_id, payload)
                tags = tags or {}
                tags["reason"] = reason
                self.stats.last_decision_reasons[persona_id] = reason
                self.stats.record_decision(persona_id=persona_id, reason=reason, tags=tags)
                if not decision:
                    if reason == "cooldown":
                        self.stats.messages_suppressed_cooldown += 1
                    elif reason == "budget":
                        self.stats.messages_suppressed_budget += 1
                    elif reason == "bot_origin":
                        self.stats.messages_suppressed_bot_origin += 1
                    continue
                memory_context, _ = self._build_memory_context(persona_id, room_id, payload.get("content", ""))
                content = self.reply_generator.generate_reply(
                    persona,
                    self.room_config,
                    payload,
                    self.state,
                    tags,
                    memory_context=memory_context,
                )
                published = await publish_chat_message(
                    self.redis,
                    settings.ingest_stream,
                    persona,
                    room_id,
                    content,
                    settings.consumer_name,
                    self.validator,
                )
                if published:
                    now_ms = int(time.time() * 1000)
                    persona_stats = self.state.get_persona_stats(persona_id)
                    persona_stats.last_spoke_at_ms = now_ms
                    persona_stats.messages_published += 1
                    self.state.record_publish(room_id, now_ms, self.budget_limit, self.budget_window_ms)
                    self.stats.messages_published += 1
                else:
                    logger.warning("Failed to publish for persona %s", persona_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error processing message %s: %s", redis_id, exc)
        finally:
            await ack(self.redis, settings.firehose_stream, settings.consumer_group, redis_id)


service = PersonaWorkerService()


@app.on_event("startup")
async def startup_event() -> None:
    await service.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await service.shutdown()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict:
    stats_payload = service.stats.as_dict(
        list(service.personas.keys()), service.room_config.get("room_id", "room:demo")
    )
    describe_fn = getattr(service.reply_generator, "describe", None)
    if callable(describe_fn):
        try:
            stats_payload.update(describe_fn())
        except Exception:  # noqa: BLE001
            stats_payload.update(
                {
                    "generation_mode": settings.generation_mode,
                    "llm_provider": None,
                    "llm_model": None,
                    "prompt_manifest_path": None,
                    "provider_config_path": None,
                }
            )
    stats_payload.update(service._memory_stats_payload())
    return stats_payload


if __name__ == "__main__":
    uvicorn.run("apps.persona_workers.src.main:app", host="0.0.0.0", port=settings.http_port, reload=False)
