import os
import socket
from dataclasses import dataclass
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(name, default)


@dataclass
class Settings:
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    ingest_stream: str = _env("INGEST_STREAM", "stream:chat.ingest")
    firehose_stream: str = _env("FIREHOSE_STREAM", "stream:chat.firehose")
    consumer_group: str = _env("CONSUMER_GROUP", "chat_gateway")
    consumer_name: str = _env("CONSUMER_NAME", socket.gethostname())
    port: int = int(_env("PORT", "8080"))
    moderation_config: Optional[str] = _env("MODERATION_CONFIG")
    content_max_length: int = int(_env("CONTENT_MAX_LENGTH", "200"))
    subscribe_timeout_s: float = float(_env("SUBSCRIBE_TIMEOUT_S", "2.0"))
    broadcast_queue_size: int = int(_env("BROADCAST_QUEUE_SIZE", "2000"))


settings = Settings()
