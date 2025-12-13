import argparse
import asyncio
import json
import random
import time
import uuid
from typing import List

import redis.asyncio as redis


def random_id() -> str:
    return uuid.uuid4().hex[:26]


def random_phrase() -> str:
    phrases = [
        "that was clean",
        "unlucky",
        "chat we saw that",
        "send it",
        "lets go",
        "big play",
        "clutch incoming",
    ]
    return random.choice(phrases)


def random_emotes() -> List[str]:
    emotes = ["KEKW", "LUL", "OMEGALUL", "Pog", "EZ", "GG"]
    return random.sample(emotes, k=random.randint(0, 2))


def build_message(room_id: str, user_idx: int) -> dict:
    display = f"viewer{user_idx:04d}"
    content = f"{random_phrase()} {random.choice(random_emotes() + [''])}".strip()
    return {
        "schema_name": "ChatMessage",
        "schema_version": "1.0.0",
        "id": random_id(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "room_id": room_id,
        "origin": "human",
        "user_id": f"user_{user_idx:04d}",
        "display_name": display,
        "content": content[:200],
        "reply_to": None,
        "mentions": [],
        "emotes": [{"code": e} for e in random_emotes()],
        "badges": ["vip"] if user_idx % 5 == 0 else [],
        "style": None,
        "client_meta": None,
        "moderation": None,
        "trace": {"producer": "stub_publisher"},
    }


async def publish_messages(args: argparse.Namespace) -> None:
    client = redis.from_url(args.redis_url, decode_responses=False)
    start = time.time()
    next_send = start
    user_ids = list(range(args.users))
    try:
        while True:
            if args.duration and (time.time() - start) > args.duration:
                break
            if args.mode == "burst":
                for _ in range(args.burst_size):
                    user_idx = random.choice(user_ids)
                    await send_one(client, args.ingest_stream, build_message(args.room_id, user_idx))
                await asyncio.sleep(max(1.0 / args.rate, 0.01))
                continue
            now = time.time()
            if now >= next_send:
                user_idx = random.choice(user_ids)
                await send_one(client, args.ingest_stream, build_message(args.room_id, user_idx))
                next_send = now + (1.0 / args.rate if args.rate else 0)
            await asyncio.sleep(0.001)
    finally:
        await client.close()


async def send_one(client: redis.Redis, stream: str, message: dict) -> None:
    payload = json.dumps(message)
    await client.xadd(stream, {"data": payload})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish stub chat messages to Redis Streams")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--room-id", default="room:demo")
    parser.add_argument("--rate", type=float, default=5.0, help="messages per second")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=int, default=0, help="seconds to run (0 = forever)")
    parser.add_argument("--mode", choices=["random", "burst"], default="random")
    parser.add_argument("--burst-size", type=int, default=50)
    parser.add_argument("--ingest-stream", default="stream:chat.ingest")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(publish_messages(args))


if __name__ == "__main__":
    main()
