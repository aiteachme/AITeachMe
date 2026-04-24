"""In-process pub/sub for workflow live streams."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any


MAX_WORKFLOW_STREAM_QUEUE_SIZE = 800


@dataclass(frozen=True)
class WorkflowStreamEvent:
    event: str
    data: dict[str, Any]


@dataclass
class _Subscriber:
    queue: asyncio.Queue[WorkflowStreamEvent]
    loop: asyncio.AbstractEventLoop


_SUBSCRIBERS: dict[str, dict[int, _Subscriber]] = {}
_SUBSCRIBERS_LOCK = RLock()
_SUBSCRIBER_IDS = itertools.count(1)


def _json_default(value: Any) -> str:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """Format one SSE event payload."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n"


def _normalize_channel(channel: str) -> str:
    return str(channel or "").strip()


def _enqueue(subscriber: _Subscriber, item: WorkflowStreamEvent) -> None:
    def put() -> None:
        while subscriber.queue.full():
            try:
                subscriber.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        subscriber.queue.put_nowait(item)

    if subscriber.loop.is_closed():
        return
    subscriber.loop.call_soon_threadsafe(put)


def publish_workflow_stream_event(channel: str, event: str, data: dict[str, Any]) -> None:
    """Publish a live event to active in-process subscribers.

    The channel is usually a normalized subject slug. Data remains opaque to
    infra; workflow/API layers decide the event names and payload schema.
    """

    normalized = _normalize_channel(channel)
    if not normalized:
        return
    item = WorkflowStreamEvent(event=str(event or "").strip() or "message", data=dict(data or {}))
    with _SUBSCRIBERS_LOCK:
        subscribers = list(_SUBSCRIBERS.get(normalized, {}).items())
    stale_ids: list[int] = []
    for subscriber_id, subscriber in subscribers:
        if subscriber.loop.is_closed():
            stale_ids.append(subscriber_id)
            continue
        _enqueue(subscriber, item)
    if stale_ids:
        with _SUBSCRIBERS_LOCK:
            current = _SUBSCRIBERS.get(normalized)
            if current is not None:
                for subscriber_id in stale_ids:
                    current.pop(subscriber_id, None)
                if not current:
                    _SUBSCRIBERS.pop(normalized, None)


@contextmanager
def subscribe_workflow_stream(channel: str) -> Iterator[asyncio.Queue[WorkflowStreamEvent]]:
    """Register a queue for one live workflow stream channel."""

    normalized = _normalize_channel(channel)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[WorkflowStreamEvent] = asyncio.Queue(maxsize=MAX_WORKFLOW_STREAM_QUEUE_SIZE)
    subscriber_id = next(_SUBSCRIBER_IDS)
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.setdefault(normalized, {})[subscriber_id] = _Subscriber(queue=queue, loop=loop)
    try:
        yield queue
    finally:
        with _SUBSCRIBERS_LOCK:
            current = _SUBSCRIBERS.get(normalized)
            if current is not None:
                current.pop(subscriber_id, None)
                if not current:
                    _SUBSCRIBERS.pop(normalized, None)


__all__ = [
    "WorkflowStreamEvent",
    "format_sse_event",
    "publish_workflow_stream_event",
    "subscribe_workflow_stream",
]
