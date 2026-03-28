"""LLM 调用追踪与可观测性。

包含：LLMCallRecord（调用记录）、Span/Tracer（操作追踪）、LLMCallTracker（统计）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import structlog

logger = structlog.get_logger()


# ── 调用记录 ──────────────────────────────────────────────────


@dataclass
class LLMCallRecord:
    """单次 LLM 调用记录。"""

    task_type: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    success: bool = True
    error: str | None = None
    call_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def estimated_cost_usd(self) -> float:
        return (self.prompt_tokens * 0.002 + self.completion_tokens * 0.006) / 1000


# ── Span 追踪 ─────────────────────────────────────────────────


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

    def finish(self) -> None:
        self.end_time = datetime.now(timezone.utc)


class Tracer:
    """追踪管理器，管理 Span 生命周期。"""

    def __init__(self) -> None:
        self._active: dict[str, Span] = {}
        self._completed: list[Span] = []

    def start_span(self, name: str, *, parent_id: str | None = None) -> Span:
        span = Span(name=name, parent_id=parent_id)
        self._active[span.span_id] = span
        return span

    def end_span(self, span_id: str) -> Span | None:
        span = self._active.pop(span_id, None)
        if span:
            span.finish()
            self._completed.append(span)
        return span

    def get_completed(self, limit: int = 100) -> list[Span]:
        return self._completed[-limit:]


# ── 调用统计 ──────────────────────────────────────────────────


class LLMCallTracker:
    """LLM 调用统计。"""

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []
        self._by_type: dict[str, list[LLMCallRecord]] = defaultdict(list)

    def record(self, rec: LLMCallRecord) -> None:
        self._records.append(rec)
        self._by_type[rec.task_type].append(rec)
        logger.info("llm_call", call_id=rec.call_id, task_type=rec.task_type,
                     model=rec.model, tokens=rec.total_tokens,
                     latency=round(rec.latency_s, 2), ok=rec.success)

    def get_summary(self) -> dict:
        if not self._records:
            return {"total_calls": 0, "total_tokens": 0}
        n = len(self._records)
        return {
            "total_calls": n,
            "total_tokens": sum(r.total_tokens for r in self._records),
            "success_rate": round(sum(1 for r in self._records if r.success) / n, 3),
            "avg_latency_s": round(sum(r.latency_s for r in self._records) / n, 2),
        }


# ── 全局单例 ──────────────────────────────────────────────────

_tracer: Tracer | None = None
_tracker: LLMCallTracker | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def get_tracker() -> LLMCallTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMCallTracker()
    return _tracker
