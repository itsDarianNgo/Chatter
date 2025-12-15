import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # Optional for local dev; containers already supply env
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency managed via Dockerfile/pyproject
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
    stream_frames_key: str = _env("STREAM_FRAMES_KEY", "stream:frames")
    stream_transcripts_key: str = _env("STREAM_TRANSCRIPTS_KEY", "stream:transcripts")
    stream_observations_key: str = _env("STREAM_OBSERVATIONS_KEY", "stream:observations")

    consumer_group: str = _env("CONSUMER_GROUP", "stream_perceptor")
    consumer_name: str = _env("CONSUMER_NAME", socket.gethostname())

    http_port: int = int(_env("HTTP_PORT", "8100"))
    log_level: str = _env("LOG_LEVEL", "INFO")

    llm_provider_config_path: str = _env("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/stub.json")
    prompt_manifest_path: str = _env("PROMPT_MANIFEST_PATH", "prompts/manifest.json")

    schema_stream_frame_path: str = _env(
        "SCHEMA_STREAM_FRAME_PATH", "packages/protocol/jsonschema/stream_frame.v1.schema.json"
    )
    schema_stream_transcript_segment_path: str = _env(
        "SCHEMA_STREAM_TRANSCRIPT_SEGMENT_PATH", "packages/protocol/jsonschema/stream_transcript_segment.v1.schema.json"
    )
    schema_stream_observation_path: str = _env(
        "SCHEMA_STREAM_OBSERVATION_PATH", "packages/protocol/jsonschema/stream_observation.v1.schema.json"
    )

    transcript_buffer_retention_ms: int = int(_env("TRANSCRIPT_BUFFER_RETENTION_MS", "120000"))
    transcript_join_window_ms: int = int(_env("TRANSCRIPT_JOIN_WINDOW_MS", "30000"))


settings = Settings()

