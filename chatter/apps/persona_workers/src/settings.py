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


def _env_optional_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv_if_present()


@dataclass
class Settings:
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    firehose_stream: str = _env("FIREHOSE_STREAM", "stream:chat.firehose")
    ingest_stream: str = _env("INGEST_STREAM", "stream:chat.ingest")
    stream_observations_key: str = _env("STREAM_OBSERVATIONS_KEY", "stream:observations")
    consumer_group: str = _env("CONSUMER_GROUP", "persona_workers")
    consumer_name: str = _env("CONSUMER_NAME", socket.gethostname())
    room_config_path: str = _env("ROOM_CONFIG_PATH", "configs/rooms/demo.json")
    persona_config_dir: str = _env("PERSONA_CONFIG_DIR", "configs/personas")
    moderation_config_path: str = _env("MODERATION_CONFIG_PATH", "configs/moderation/default.json")
    generation_mode: str = _env("GENERATION_MODE", "deterministic")
    llm_provider_config_path: str = _env("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/stub.json")
    prompt_manifest_path: str = _env("PROMPT_MANIFEST_PATH", "prompts/manifest.json")
    chat_reply_prompt_id: str = _env("CHAT_REPLY_PROMPT_ID", "persona_chat_reply_v2")
    schema_chat_message_path: str = _env(
        "SCHEMA_CHAT_MESSAGE_PATH", "packages/protocol/jsonschema/chat_message.schema.json"
    )
    schema_stream_observation_path: str = _env(
        "SCHEMA_STREAM_OBSERVATION_PATH", "packages/protocol/jsonschema/stream_observation.v1.schema.json"
    )
    schema_room_path: str = _env("SCHEMA_ROOM_PATH", "configs/schemas/room.schema.json")
    schema_persona_path: str = _env("SCHEMA_PERSONA_PATH", "configs/schemas/persona.schema.json")
    schema_observation_context_path: str = _env(
        "SCHEMA_OBSERVATION_CONTEXT_PATH", "configs/schemas/observation_context.schema.json"
    )
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
    mem0_api_key: str | None = _env("MEM0_API_KEY")
    mem0_base_url: str = _env("MEM0_BASE_URL", "https://api.mem0.ai")
    mem0_app_id: str | None = _env("MEM0_APP_ID")
    mem0_org_id: str | None = _env("MEM0_ORG_ID")
    mem0_project_id: str | None = _env("MEM0_PROJECT_ID")
    mem0_timeout_s: int = int(_env("MEM0_TIMEOUT_S", "10"))

    max_recent_messages_per_room: int = int(_env("MAX_RECENT_MESSAGES_PER_ROOM", "50"))
    dedupe_cache_size: int = int(_env("DEDUPE_CACHE_SIZE", "1000"))
    max_react_age_s: float = float(_env("MAX_REACT_AGE_S", "20"))
    persona_cooldown_ms_default: int = int(_env("PERSONA_COOLDOWN_MS_DEFAULT", "1500"))
    room_bot_budget_per_10s_default: int = int(_env("ROOM_BOT_BUDGET_PER_10S_DEFAULT", "5"))
    obs_context_config_path: str = _env(
        "OBS_CONTEXT_CONFIG_PATH", "/app/configs/observation_context/default.json"
    )
    auto_commentary_config_path: str = _env(
        "AUTO_COMMENTARY_CONFIG_PATH", "/app/configs/auto_commentary/default.json"
    )
    auto_commentary_enabled_override: Optional[bool] = _env_optional_bool("AUTO_COMMENTARY_ENABLED")


def load_settings() -> Settings:
    return Settings()


settings = load_settings()
