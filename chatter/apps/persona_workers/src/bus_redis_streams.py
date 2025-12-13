import asyncio
import logging
from typing import List, Tuple

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)


async def connect(redis_url: str) -> redis.Redis:
    client = redis.from_url(redis_url, decode_responses=True)
    await client.ping()
    return client


async def ensure_consumer_group(client: redis.Redis, stream: str, group: str) -> None:
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
        logger.info("Created consumer group %s on %s", group, stream)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return
        raise


async def read_messages(
    client: redis.Redis, stream: str, group: str, consumer_name: str, count: int = 10, block_ms: int = 1000
) -> List[Tuple[str, str]]:
    try:
        records = await client.xreadgroup(
            groupname=group,
            consumername=consumer_name,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
    except RedisConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read from stream %s: %s", stream, exc)
        await asyncio.sleep(1)
        return []
    if not records:
        return []
    messages: List[Tuple[str, str]] = []
    for _stream, entries in records:
        for redis_id, fields in entries:
            raw = fields.get("data")
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8")
                except Exception:  # noqa: BLE001
                    raw = None
            if not isinstance(raw, str):
                await ack(client, stream, group, redis_id)
                continue
            messages.append((redis_id, raw))
    return messages


async def ack(client: redis.Redis, stream: str, group: str, redis_id: str) -> None:
    try:
        await client.xack(stream, group, redis_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to ack %s: %s", redis_id, exc)
