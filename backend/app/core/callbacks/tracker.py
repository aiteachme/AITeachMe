"""LLM 调用统计追踪器。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import structlog

from app.core.callbacks.records import LLMCallRecord

logger = structlog.get_logger()


class LLMCallTracker:
    """收集 LLM 调用指标，输出 structlog 日志并提供内存统计。"""

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []
        self._by_task_type: dict[str, list[LLMCallRecord]] = defaultdict(list)

    def record(self, rec: LLMCallRecord) -> None:
        self._records.append(rec)
        self._by_task_type[rec.task_type].append(rec)
        logger.info(
            "llm_call_tracked",
            call_id=rec.call_id, task_type=rec.task_type, model=rec.model,
            prompt_tokens=rec.prompt_tokens, completion_tokens=rec.completion_tokens,
            total_tokens=rec.total_tokens, latency_s=round(rec.latency_s, 2), success=rec.success,
        )

    def get_summary(self, since: datetime | None = None) -> dict:
        records = self._records if since is None else [r for r in self._records if r.timestamp >= since]
        if not records:
            return {"total_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0, "success_rate": 1.0, "by_task_type": {}}

        total_calls = len(records)
        by_type: dict[str, dict] = {}
        for tt, recs in self._by_task_type.items():
            filtered = recs if since is None else [r for r in recs if r.timestamp >= since]
            if filtered:
                by_type[tt] = {
                    "calls": len(filtered),
                    "tokens": sum(r.total_tokens for r in filtered),
                    "avg_latency_s": round(sum(r.latency_s for r in filtered) / len(filtered), 2),
                }
        return {
            "total_calls": total_calls,
            "total_tokens": sum(r.total_tokens for r in records),
            "total_cost_usd": round(sum(r.estimated_cost_usd for r in records), 4),
            "success_rate": round(sum(1 for r in records if r.success) / total_calls, 3),
            "avg_latency_s": round(sum(r.latency_s for r in records) / total_calls, 2),
            "by_task_type": by_type,
        }

    def clear(self) -> None:
        self._records.clear()
        self._by_task_type.clear()


_tracker: LLMCallTracker | None = None


def get_tracker() -> LLMCallTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMCallTracker()
    return _tracker
