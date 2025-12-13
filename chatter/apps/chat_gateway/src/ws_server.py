import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from typing import Any, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self, max_queue_size: int = 2000) -> None:
        self.rooms: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.broadcast_queue: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue(maxsize=max_queue_size)
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._broadcast_worker())

    async def shutdown(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        self.rooms[room_id].add(websocket)
        logger.info("WebSocket connected to %s", room_id)

    def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        if websocket in self.rooms.get(room_id, set()):
            self.rooms[room_id].remove(websocket)
        if not self.rooms.get(room_id):
            self.rooms.pop(room_id, None)
        logger.info("WebSocket disconnected from %s", room_id)

    async def enqueue_broadcast(self, room_id: str, message: Dict[str, Any]) -> bool:
        try:
            self.broadcast_queue.put_nowait((room_id, message))
            return True
        except asyncio.QueueFull:
            logger.warning("Broadcast queue full; dropping message for %s", room_id)
            return False

    async def _broadcast_worker(self) -> None:
        while True:
            room_id, message = await self.broadcast_queue.get()
            websockets = list(self.rooms.get(room_id, []))
            if not websockets:
                continue
            send_tasks = [ws.send_text(json.dumps(message)) for ws in websockets]
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            for ws, result in zip(websockets, results, strict=False):
                if isinstance(result, Exception):
                    logger.info("Removing dead websocket from %s: %s", room_id, result)
                    self.disconnect(ws, room_id)

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self.rooms.values())

    async def handle_client(self, websocket: WebSocket, default_room: str, subscribe_timeout: float) -> None:
        room = default_room
        try:
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=subscribe_timeout)
                data = json.loads(text)
                if isinstance(data, dict) and data.get("type") == "subscribe" and isinstance(data.get("room_id"), str):
                    room = data["room_id"]
            except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
                pass
            await self.connect(websocket, room)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            self.disconnect(websocket, room)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket error: %s", exc)
            self.disconnect(websocket, room)
