"""In-process pub/sub used to stream agent activity to the UI over SSE.

Single-process by design. In production this would be Redis pub/sub (or the
job runner's own event stream) - see "What I would build next" in the README.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

MAX_REPLAY = 200


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._replay: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_REPLAY))
        self._seq = 0

    def subscribe(self, migration_ref: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[migration_ref].add(queue)
        for event in self._replay[migration_ref]:
            queue.put_nowait(event)
        return queue

    def unsubscribe(self, migration_ref: str, queue: asyncio.Queue) -> None:
        self._subscribers[migration_ref].discard(queue)

    def publish(self, migration_ref: str, event_type: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        event = {
            "seq": self._seq,
            "type": event_type,
            "migration_id": migration_ref,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._replay[migration_ref].append(event)
        for queue in list(self._subscribers[migration_ref]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                self._subscribers[migration_ref].discard(queue)

    def clear(self, migration_ref: str) -> None:
        self._replay.pop(migration_ref, None)

    @staticmethod
    def to_sse(event: dict) -> str:
        data = json.dumps(event, default=str)
        return f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n"


bus = EventBus()
