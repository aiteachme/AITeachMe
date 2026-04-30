"""Pub/sub helpers for workflow live streams."""

from __future__ import annotations

import asyncio
import itertools
import json
import queue
import select
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any

from app.shared.infra.env_support import get_env, get_env_bool, get_env_bounded_float, get_env_bounded_int


MAX_WORKFLOW_STREAM_QUEUE_SIZE = get_env_bounded_int("WORKFLOW_STREAM_QUEUE_SIZE", 800, min_value=100, max_value=10000)
MAX_POSTGRES_NOTIFY_QUEUE_SIZE = get_env_bounded_int(
    "WORKFLOW_STREAM_POSTGRES_NOTIFY_QUEUE_SIZE",
    2000,
    min_value=100,
    max_value=20000,
)
POSTGRES_NOTIFY_PAYLOAD_LIMIT_BYTES = get_env_bounded_int(
    "WORKFLOW_STREAM_POSTGRES_NOTIFY_PAYLOAD_LIMIT_BYTES",
    7000,
    min_value=1000,
    max_value=7900,
)
POSTGRES_NOTIFY_CHANNEL = "atm_workflow_stream"
POSTGRES_NOTIFY_RECONNECT_DELAY_S = get_env_bounded_float(
    "WORKFLOW_STREAM_POSTGRES_RECONNECT_DELAY_S",
    2.0,
    min_value=0.2,
    max_value=30.0,
)
_PROCESS_ID = uuid.uuid4().hex


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
_POSTGRES_PUBLISH_QUEUE: queue.Queue[str | None] | None = None
_POSTGRES_PUBLISH_THREAD: threading.Thread | None = None
_POSTGRES_LISTENER_THREAD: threading.Thread | None = None
_POSTGRES_BRIDGE_LOCK = RLock()
_POSTGRES_BRIDGE_DISABLED = False


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


def _postgres_dsn() -> str:
    dsn = (get_env("DATABASE_URL") or "").strip()
    if not dsn:
        return ""
    for driver_prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql+asyncpg://",
    ):
        if dsn.startswith(driver_prefix):
            return "postgresql://" + dsn[len(driver_prefix):]
    return dsn


def _postgres_bridge_enabled() -> bool:
    if _POSTGRES_BRIDGE_DISABLED:
        return False
    if not get_env_bool("WORKFLOW_STREAM_POSTGRES_BRIDGE_ENABLED", True):
        return False
    dsn = _postgres_dsn()
    if not dsn:
        return False
    try:
        from app.shared.infra.database import is_postgres

        return bool(is_postgres())
    except Exception:
        return False


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


def _publish_inprocess_event(channel: str, event: str, data: dict[str, Any]) -> WorkflowStreamEvent | None:
    normalized = _normalize_channel(channel)
    if not normalized:
        return None
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
    return item


def _build_postgres_notify_payload(channel: str, item: WorkflowStreamEvent) -> str | None:
    payload = json.dumps(
        {
            "origin": _PROCESS_ID,
            "channel": channel,
            "event": item.event,
            "data": item.data,
        },
        ensure_ascii=False,
        default=_json_default,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > POSTGRES_NOTIFY_PAYLOAD_LIMIT_BYTES:
        return None
    return payload


def _postgres_publish_worker(notify_queue: queue.Queue[str | None]) -> None:
    conn = None
    cursor = None
    while True:
        payload = notify_queue.get()
        if payload is None:
            break
        if not _postgres_bridge_enabled():
            continue
        try:
            if conn is None:
                import psycopg2
                from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

                conn = psycopg2.connect(_postgres_dsn())
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                cursor = conn.cursor()
            cursor.execute("SELECT pg_notify(%s, %s)", (POSTGRES_NOTIFY_CHANNEL, payload))
        except Exception:
            try:
                if cursor is not None:
                    cursor.close()
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            cursor = None
            conn = None
            time.sleep(POSTGRES_NOTIFY_RECONNECT_DELAY_S)


def _ensure_postgres_publisher() -> queue.Queue[str | None] | None:
    global _POSTGRES_PUBLISH_QUEUE, _POSTGRES_PUBLISH_THREAD
    if not _postgres_bridge_enabled():
        return None
    with _POSTGRES_BRIDGE_LOCK:
        if _POSTGRES_PUBLISH_QUEUE is None:
            _POSTGRES_PUBLISH_QUEUE = queue.Queue(maxsize=MAX_POSTGRES_NOTIFY_QUEUE_SIZE)
        if _POSTGRES_PUBLISH_THREAD is None or not _POSTGRES_PUBLISH_THREAD.is_alive():
            _POSTGRES_PUBLISH_THREAD = threading.Thread(
                target=_postgres_publish_worker,
                args=(_POSTGRES_PUBLISH_QUEUE,),
                name="workflow-stream-pg-publisher",
                daemon=True,
            )
            _POSTGRES_PUBLISH_THREAD.start()
        return _POSTGRES_PUBLISH_QUEUE


def _publish_postgres_event(channel: str, item: WorkflowStreamEvent) -> None:
    notify_queue = _ensure_postgres_publisher()
    if notify_queue is None:
        return
    payload = _build_postgres_notify_payload(channel, item)
    if payload is None:
        return
    try:
        notify_queue.put_nowait(payload)
    except queue.Full:
        try:
            notify_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            notify_queue.put_nowait(payload)
        except queue.Full:
            pass


def _handle_postgres_notification(raw_payload: str) -> None:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    if str(payload.get("origin") or "") == _PROCESS_ID:
        return
    channel = _normalize_channel(str(payload.get("channel") or ""))
    event = str(payload.get("event") or "").strip()
    data = payload.get("data")
    if not channel or not event or not isinstance(data, dict):
        return
    _publish_inprocess_event(channel, event, data)


def _postgres_listener_worker() -> None:
    while True:
        if not _postgres_bridge_enabled():
            time.sleep(POSTGRES_NOTIFY_RECONNECT_DELAY_S)
            continue
        conn = None
        cursor = None
        try:
            import psycopg2
            from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

            conn = psycopg2.connect(_postgres_dsn())
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            cursor.execute(f"LISTEN {POSTGRES_NOTIFY_CHANNEL}")
            while True:
                if select.select([conn], [], [], 5.0) == ([], [], []):
                    continue
                conn.poll()
                while conn.notifies:
                    notification = conn.notifies.pop(0)
                    _handle_postgres_notification(str(notification.payload or ""))
        except Exception:
            try:
                if cursor is not None:
                    cursor.close()
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            time.sleep(POSTGRES_NOTIFY_RECONNECT_DELAY_S)


def _ensure_postgres_listener() -> None:
    global _POSTGRES_LISTENER_THREAD
    if not _postgres_bridge_enabled():
        return
    with _POSTGRES_BRIDGE_LOCK:
        if _POSTGRES_LISTENER_THREAD is not None and _POSTGRES_LISTENER_THREAD.is_alive():
            return
        _POSTGRES_LISTENER_THREAD = threading.Thread(
            target=_postgres_listener_worker,
            name="workflow-stream-pg-listener",
            daemon=True,
        )
        _POSTGRES_LISTENER_THREAD.start()


def publish_workflow_stream_event(channel: str, event: str, data: dict[str, Any]) -> None:
    """Publish a live event to active workflow stream subscribers.

    Local mode uses in-process queues. In PostgreSQL cloud mode the event is
    also bridged through LISTEN/NOTIFY so background tasks and SSE connections
    can live in different workers or pods without falling back to slow snapshots.
    """

    normalized = _normalize_channel(channel)
    item = _publish_inprocess_event(normalized, event, data)
    if item is not None:
        _publish_postgres_event(normalized, item)


@contextmanager
def subscribe_workflow_stream(channel: str) -> Iterator[asyncio.Queue[WorkflowStreamEvent]]:
    """Register a queue for one live workflow stream channel."""

    normalized = _normalize_channel(channel)
    _ensure_postgres_listener()
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
