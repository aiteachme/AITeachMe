"""兼容性 shim — 实际实现已移至 app.teaching.events。"""
from app.teaching.events import (  # noqa: F401
    EventType,
    TeachingEvent,
    count_events,
    emit_event,
    get_events,
)
