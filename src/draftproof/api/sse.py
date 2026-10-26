"""Server-Sent Event encoding and replay."""

from __future__ import annotations

import json
from typing import Any


def format_event(seq: int, event_type: str, data: dict[str, Any], at: str | None = None) -> str:
    """Encode one SSE frame including the replay id."""
    payload = dict(data)
    if at:
        payload["_at"] = at
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {event_type}\ndata: {rendered}\n\n"


def format_comment(text: str = "keep-alive") -> str:
    """Encode an SSE comment used as a heartbeat."""
    return f": {text}\n\n"


def format_end(reason: str = "complete") -> str:
    """Encode the terminal frame of a stream."""
    return f"event: stream_end\ndata: {json.dumps({'reason': reason})}\n\n"
