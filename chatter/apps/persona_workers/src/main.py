import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import uvicorn
from fastapi import FastAPI

from .bus_redis_streams import ack, connect, ensure_consumer_group, read_messages
from .config_loader import ConfigLoader
from .generator_stub import generate_reply
from .policy import should_speak
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

    async def start(self) -> None:
        await self._connect()
        asyncio.create_task(self._run())

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

            if self.state.seen_before(message_id):
                self.stats.messages_deduped += 1
                return

            self.validator.validate(payload)

            budget_limit = settings.room_bot_budget_per_10s_default
            budget_window_ms = 10_000
            self.state.add_recent_message(room_id, payload, budget_limit, budget_window_ms)

            for persona_id, persona in self.personas.items():
                decision, reason = self._evaluate_persona(room_id, persona_id, payload, budget_limit, budget_window_ms)
                self.stats.last_decision_reasons[persona_id] = reason
                if not decision:
                    continue
                content = generate_reply(
                    persona,
                    room_id,
                    payload,
                    persona.get("safety", {}).get("max_chars", 200),
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
                    self.state.record_publish(room_id, now_ms, budget_limit, budget_window_ms)
                    self.stats.messages_published += 1
                else:
                    logger.warning("Failed to publish for persona %s", persona_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error processing message %s: %s", redis_id, exc)
        finally:
            await ack(self.redis, settings.firehose_stream, settings.consumer_group, redis_id)

    def _evaluate_persona(
        self, room_id: str, persona_id: str, payload: Dict[str, Any], budget_limit: int, budget_window_ms: int
    ) -> Tuple[bool, str]:
        cooldown_ms = int(self.room_config.get("timing", {}).get("soft_cooldown_ms", settings.persona_cooldown_ms_default))
        decision, reason = should_speak(
            room_id,
            persona_id,
            payload,
            self.state,
            max_react_age_s=settings.max_react_age_s,
            persona_cooldown_ms=cooldown_ms,
            budget_limit=budget_limit,
            budget_window_ms=budget_window_ms,
        )
        if reason == "cooldown":
            self.stats.messages_suppressed_cooldown += 1
        elif reason == "budget":
            self.stats.messages_suppressed_budget += 1
        elif reason == "bot_origin":
            self.stats.messages_suppressed_bot_origin += 1
        return decision, reason


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
    return service.stats.as_dict(list(service.personas.keys()), service.room_config.get("room_id", "room:demo"))


if __name__ == "__main__":
    uvicorn.run("apps.persona_workers.src.main:app", host="0.0.0.0", port=settings.http_port, reload=False)
