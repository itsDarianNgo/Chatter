import asyncio
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .bus_redis_streams import RedisBus, Stats
from .safety import SafetyProcessor
from .settings import settings
from .validator import ChatMessageValidator
from .ws_server import WebSocketManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="chat_gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ws_manager = WebSocketManager(max_queue_size=settings.broadcast_queue_size)
stats = Stats()
schema_path = Path(__file__).resolve().parents[3] / "packages" / "protocol" / "jsonschema" / "chat_message.schema.json"
validator = ChatMessageValidator(schema_path)
moderation_path = Path(settings.moderation_config) if settings.moderation_config else None
safety = SafetyProcessor(settings.content_max_length, moderation_path)
bus = RedisBus(
    redis_url=settings.redis_url,
    ingest_stream=settings.ingest_stream,
    firehose_stream=settings.firehose_stream,
    consumer_group=settings.consumer_group,
    consumer_name=settings.consumer_name,
    validator=validator,
    safety=safety,
    ws_manager=ws_manager,
    stats=stats,
)


@app.on_event("startup")
async def startup_event() -> None:
    await ws_manager.start()
    asyncio.create_task(bus.run())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await ws_manager.shutdown()
    await bus.stop()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
async def stats_endpoint() -> dict[str, int]:
    return stats.as_dict(ws_manager.active_connections)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await ws_manager.handle_client(websocket, default_room="room:demo", subscribe_timeout=settings.subscribe_timeout_s)


if __name__ == "__main__":
    uvicorn.run("apps.chat_gateway.src.main:app", host="0.0.0.0", port=settings.port, reload=False)
