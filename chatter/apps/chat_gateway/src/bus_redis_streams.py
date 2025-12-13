import asyncio
import json
import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from .safety import SafetyProcessor
from .validator import ChatMessageValidator
from .ws_server import WebSocketManager

logger = logging.getLogger(__name__)


class Stats:
    def __init__(self) -> None:
        self.messages_consumed = 0
        self.messages_broadcast = 0
        self.messages_dropped = 0

    def as_dict(self, active_ws: int) -> Dict[str, Any]:
        return {
            "messages_consumed": self.messages_consumed,
            "messages_broadcast": self.messages_broadcast,
            "messages_dropped": self.messages_dropped,
            "active_ws_connections": active_ws,
        }


class RedisBus:
    def __init__(
        self,
        redis_url: str,
        ingest_stream: str,
        firehose_stream: str,
        consumer_group: str,
        consumer_name: str,
        validator: ChatMessageValidator,
        safety: SafetyProcessor,
        ws_manager: WebSocketManager,
        stats: Stats,
    ) -> None:
        self.redis_url = redis_url
        self.ingest_stream = ingest_stream
        self.firehose_stream = firehose_stream
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.validator = validator
        self.safety = safety
        self.ws_manager = ws_manager
        self.stats = stats
        self.client: Optional[redis.Redis] = None
        self._stop = asyncio.Event()

    async def connect(self) -> None:
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        await self._ensure_group()
        logger.info("Connected to Redis at %s", self.redis_url)

    async def _ensure_group(self) -> None:
        assert self.client is not None
        try:
            await self.client.xgroup_create(self.ingest_stream, self.consumer_group, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", self.consumer_group, self.ingest_stream)
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return
            raise

    async def stop(self) -> None:
        self._stop.set()
        if self.client:
            await self.client.close()

    async def run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                if not self.client:
                    await self.connect()
                await self._consume_loop()
            except (RedisConnectionError, ConnectionError):
                logger.warning("Redis connection lost; retrying in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                self.client = None
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in bus loop: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _consume_loop(self) -> None:
        assert self.client is not None
        while not self._stop.is_set():
            records = await self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams={self.ingest_stream: ">"},
                count=50,
                block=1000,
            )
            if not records:
                continue
            for _stream, messages in records:
                for message_id, fields in messages:
                    await self._handle_message(message_id, fields)

    async def _handle_message(self, message_id: str, fields: Dict[str, Any]) -> None:
        assert self.client is not None
        self.stats.messages_consumed += 1
        raw = fields.get("data")
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not isinstance(raw, str):
                raise ValueError("missing data field")
            payload = json.loads(raw)
            self.validator.validate(payload)
            sanitized = self.safety.process(payload)
            if not sanitized:
                self.stats.messages_dropped += 1
                return
            sent = await self.ws_manager.enqueue_broadcast(sanitized.get("room_id", "room:demo"), sanitized)
            if sent:
                self.stats.messages_broadcast += 1
            else:
                self.stats.messages_dropped += 1
            await self.client.xadd(self.firehose_stream, {"data": json.dumps(sanitized)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to process message %s: %s", message_id, exc)
            self.stats.messages_dropped += 1
        finally:
            try:
                await self.client.xack(self.ingest_stream, self.consumer_group, message_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to ack %s: %s", message_id, exc)
