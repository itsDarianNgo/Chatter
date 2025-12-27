import json
import logging
from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

import redis.asyncio as redis

from .validator import ChatMessageValidator

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_chat_message(
    persona: Dict, room_id: str, content: str, consumer_name: str, producer: str = "persona_worker"
) -> Dict:
    return {
        "schema_name": "ChatMessage",
        "schema_version": "1.0.0",
        "id": _generate_id(),
        "ts": _now_iso(),
        "room_id": room_id,
        "origin": "bot",
        "user_id": persona.get("persona_id"),
        "display_name": persona.get("display_name"),
        "content": content,
        "reply_to": None,
        "mentions": [],
        "emotes": [],
        "badges": persona.get("presentation", {}).get("badges", []),
        "style": persona.get("presentation", {}).get("style"),
        "client_meta": None,
        "moderation": None,
        "trace": {
            "producer": producer,
            "persona_id": persona.get("persona_id"),
            "worker_instance": consumer_name,
        },
    }


def _generate_id() -> str:
    return uuid4().hex


async def publish_chat_message(
    client: redis.Redis,
    ingest_stream: str,
    persona: Dict,
    room_id: str,
    content: str,
    consumer_name: str,
    validator: ChatMessageValidator,
    trace_producer: str = "persona_worker",
) -> bool:
    message = build_chat_message(persona, room_id, content, consumer_name, producer=trace_producer)
    try:
        validator.validate(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Generated message failed validation: %s", exc)
        return False
    try:
        await client.xadd(ingest_stream, {"data": json.dumps(message)})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to publish message: %s", exc)
        return False
