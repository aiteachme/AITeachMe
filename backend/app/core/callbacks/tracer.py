"""Span 追踪器，提供类似 OpenTelemetry 的操作追踪能力。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import structlog

from app.core.callbacks.records import LLMCallRecord

logger = structlog.get_logger()


@dataclass
class Span:
    """一个可追踪的操作单元。"""

    name: str
    span_id: str = field(default_factory=lambda: uuid4().hex[:12])
    parent_id: str | None = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    metadata: dict = field(default_factory=dict)
    events: list[LLMCallRecord] = field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def add_event(self, record: LLMCallRecord) -> None:
        self.events.append(record)

    def finish(self) -> None:
        self.end_time = datetime.now(timezone.utc)


class Tracer:
    """追踪管理器，收集 Span 树。"""

    def __init__(self) -> None:
        self._active_spans: dict[str, Span] = {}
        self._completed_spans: list[Span] = []

    def start_span(self, name: str, *, parent_id: str | None = None, metadata: dict | None = None) -> Span:
        span = Span(name=name, parent_id=parent_id, metadata=metadata or {})
        self._active_spans[span.span_id] = span
        logger.debug("span_started", span_id=span.span_id, name=name)
        return span

    def end_span(self, span_id: str) -> Span | None:
        span = self._active_spans.pop(span_id, None)
        if span is None:
            return None
        span.finish()
        self._completed_spans.append(span)
        logger.debug("span_ended", span_id=span.span_id, name=span.name, duration_s=span.duration_s)
        return span

    def record_llm_call(self, span_id: str, record: LLMCallRecord) -> None:
        span = self._active_spans.get(span_id)
        if span is not None:
            span.add_event(record)

    def get_completed_spans(self, limit: int = 100) -> list[Span]:
        return self._completed_spans[-limit:]

    def clear(self) -> None:
        self._active_spans.clear()
        self._completed_spans.clear()


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
