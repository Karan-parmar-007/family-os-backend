"""In-process SSE pub/sub for notification events (single-replica)."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from uuid import UUID

_subscribers: dict[UUID, list[asyncio.Queue[str]]] = defaultdict(list)


def subscribe(user_id: UUID) -> asyncio.Queue[str]:
    queue: asyncio.Queue[str] = asyncio.Queue()
    _subscribers[user_id].append(queue)
    return queue


def unsubscribe(user_id: UUID, queue: asyncio.Queue[str]) -> None:
    subs = _subscribers.get(user_id)
    if not subs:
        return
    try:
        subs.remove(queue)
    except ValueError:
        pass


async def publish_notification_event(user_id: UUID, event: dict) -> None:
    data = json.dumps(event)
    for queue in list(_subscribers.get(user_id, [])):
        await queue.put(data)
