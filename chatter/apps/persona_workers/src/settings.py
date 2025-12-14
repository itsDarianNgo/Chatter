import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # Optional for local dev; containers already supply env
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency managed via pyproject
    load_dotenv = None


def _load_dotenv_if_present() -> None:
    if load_dotenv is None:
        return
    project_root = Path(__file__).resolve().parents[3]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(name, default)


_load_dotenv_if_present()


@dataclass
class Settings:
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    firehose_stream: str = _env("FIREHOSE_STREAM", "stream:chat.firehose")
    ingest_stream: str = _env("INGEST_STREAM", "stream:chat.ingest")
    consumer_group: str = _env("CONSUMER_GROUP", "persona_workers")
    consumer_name: str = _env("CONSUMER_NAME", socket.gethostname())
    room_config_path: str = _env("ROOM_CONFIG_PATH", "configs/rooms/demo.json")
    persona_config_dir: str = _env("PERSONA_CONFIG_DIR", "configs/personas")
    moderation_config_path: str = _env("MODERATION_CONFIG_PATH", "configs/moderation/default.json")
    generation_mode: str = _env("GENERATION_MODE", "deterministic")
    llm_provider_config_path: str = _env("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/stub.json")
    prompt_manifest_path: str = _env("PROMPT_MANIFEST_PATH", "prompts/manifest.json")
    schema_chat_message_path: str = _env(
        "SCHEMA_CHAT_MESSAGE_PATH", "packages/protocol/jsonschema/chat_message.schema.json"
    )
    schema_room_path: str = _env("SCHEMA_ROOM_PATH", "configs/schemas/room.schema.json")
    schema_persona_path: str = _env("SCHEMA_PERSONA_PATH", "configs/schemas/persona.schema.json")
    http_port: int = int(_env("HTTP_PORT", "8090"))
    log_level: str = _env("LOG_LEVEL", "INFO")

    memory_enabled: bool = _env("MEMORY_ENABLED", "false").lower() == "true"
    memory_backend: str = _env("MEMORY_BACKEND", "stub")
    memory_policy_path: str = _env("MEMORY_POLICY_PATH", "configs/memory/default_policy.json")
    memory_fixtures_path: str = _env("MEMORY_FIXTURES_PATH", "data/memory_stub/fixtures/demo.json")
    memory_max_items: int = int(_env("MEMORY_MAX_ITEMS", "5"))
    memory_max_chars: int = int(_env("MEMORY_MAX_CHARS", "800"))
    memory_extract_strategy: str = _env("MEMORY_EXTRACT_STRATEGY", "heuristic")
    memory_scope_user_enabled: bool = _env("MEMORY_SCOPE_USER_ENABLED", "false").lower() == "true"

    max_recent_messages_per_room: int = int(_env("MAX_RECENT_MESSAGES_PER_ROOM", "50"))
    dedupe_cache_size: int = int(_env("DEDUPE_CACHE_SIZE", "1000"))
    max_react_age_s: float = float(_env("MAX_REACT_AGE_S", "20"))
    persona_cooldown_ms_default: int = int(_env("PERSONA_COOLDOWN_MS_DEFAULT", "1500"))
    room_bot_budget_per_10s_default: int = int(_env("ROOM_BOT_BUDGET_PER_10S_DEFAULT", "5"))


def load_settings() -> Settings:
    return Settings()


settings = load_settings()
