from typing import Dict


def generate_reply(persona: Dict, room_id: str, last_message: Dict, max_chars: int) -> str:
    content = last_message.get("content", "") or ""
    marker = None
    for token in ["E2E_TEST_", "E2E_MARKER_"]:
        if token in content:
            marker = token
            break
    if marker:
        reply = f"got it: {marker} ✅"
    else:
        reply = f"On it in {room_id} — acknowledged."
    if len(reply) > max_chars:
        reply = reply[:max_chars]
    return " ".join(reply.split())
