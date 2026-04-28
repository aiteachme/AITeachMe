"""In-memory tracking helpers for workflow-scoped LLM calls."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from app.shared.infra.observability.defaults import DEFAULT_LLM_OBSERVABILITY_MAX_RECORDS
from app.shared.infra.settings import get_settings

logger = structlog.get_logger()


@dataclass
class LLMCallRecord:
    """One recorded LLM call."""

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
    subject_id: str = ""
    build_session_id: str = ""
    workflow: str = ""
    lane: str = ""
    node: str = ""


class LLMCallTracker:
    """In-memory tracker for workflow-scoped LLM calls."""

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []

    def record(self, rec: LLMCallRecord) -> None:
        self._records.append(rec)
        max_records = max(1, int(DEFAULT_LLM_OBSERVABILITY_MAX_RECORDS))
        overflow = len(self._records) - max_records
        if overflow > 0:
            del self._records[:overflow]
        logger.info(
            "llm_call",
            call_id=rec.call_id,
            task_type=rec.task_type,
            model=rec.model,
            tokens=rec.total_tokens,
            latency=round(rec.latency_s, 2),
            ok=rec.success,
            subject_id=rec.subject_id,
            build_session_id=rec.build_session_id,
            workflow=rec.workflow,
            lane=rec.lane,
            node=rec.node,
        )

    def get_summary(
        self,
        *,
        build_session_id: str | None = None,
        subject_id: str | None = None,
        workflow: str | None = None,
        lane: str | None = None,
        node: str | None = None,
    ) -> dict[str, Any]:
        records = self._filter_records(
            build_session_id=build_session_id,
            subject_id=subject_id,
            workflow=workflow,
            lane=lane,
            node=node,
        )
        if not records:
            return self._empty_summary()

        settings = get_settings()
        light_model = ""
        if settings.models.light:
            light_model = settings.models.light

        total_latency_ms = int(round(sum(record.latency_s for record in records) * 1000))
        total_calls = len(records)
        failed_call_count = sum(1 for record in records if not record.success)
        prompt_tokens = sum(record.prompt_tokens for record in records)
        completion_tokens = sum(record.completion_tokens for record in records)
        total_tokens = sum(record.total_tokens for record in records)
        tokens_by_model: dict[str, int] = defaultdict(int)
        tokens_by_task_type: dict[str, int] = defaultdict(int)
        tokens_by_lane: dict[str, int] = defaultdict(int)
        tokens_by_node: dict[str, int] = defaultdict(int)
        call_count_by_model: dict[str, int] = defaultdict(int)
        call_count_by_task_type: dict[str, int] = defaultdict(int)
        call_count_by_lane: dict[str, int] = defaultdict(int)
        call_count_by_node: dict[str, int] = defaultdict(int)
        model_usage: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "call_count": 0,
                "failed_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_latency_ms": 0,
            }
        )

        light_model_call_count = 0
        light_model_total_tokens = 0
        light_task_call_count = 0
        light_task_total_tokens = 0

        for record in records:
            model_key = record.model or "(unknown_model)"
            task_key = record.task_type or "(unknown_task)"
            lane_key = record.lane or "(unknown_lane)"
            node_key = record.node or "(unknown_node)"
            latency_ms = int(round(record.latency_s * 1000))

            tokens_by_model[model_key] += record.total_tokens
            tokens_by_task_type[task_key] += record.total_tokens
            tokens_by_lane[lane_key] += record.total_tokens
            tokens_by_node[node_key] += record.total_tokens

            call_count_by_model[model_key] += 1
            call_count_by_task_type[task_key] += 1
            call_count_by_lane[lane_key] += 1
            call_count_by_node[node_key] += 1

            model_usage_row = model_usage[model_key]
            model_usage_row["call_count"] += 1
            model_usage_row["failed_call_count"] += 0 if record.success else 1
            model_usage_row["prompt_tokens"] += record.prompt_tokens
            model_usage_row["completion_tokens"] += record.completion_tokens
            model_usage_row["total_tokens"] += record.total_tokens
            model_usage_row["total_latency_ms"] += latency_ms

            if light_model and record.model == light_model:
                light_model_call_count += 1
                light_model_total_tokens += record.total_tokens
            if record.task_type in {"docgen_light", "extract", "summarize", "classify"}:
                light_task_call_count += 1
                light_task_total_tokens += record.total_tokens

        return {
            "total_calls": total_calls,
            "failed_call_count": failed_call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency_ms,
            "avg_latency_ms": round(total_latency_ms / total_calls, 2) if total_calls else 0.0,
            "tokens_by_model": dict(sorted(tokens_by_model.items())),
            "tokens_by_task_type": dict(sorted(tokens_by_task_type.items())),
            "tokens_by_lane": dict(sorted(tokens_by_lane.items())),
            "tokens_by_node": dict(sorted(tokens_by_node.items())),
            "call_count_by_model": dict(sorted(call_count_by_model.items())),
            "call_count_by_task_type": dict(sorted(call_count_by_task_type.items())),
            "call_count_by_lane": dict(sorted(call_count_by_lane.items())),
            "call_count_by_node": dict(sorted(call_count_by_node.items())),
            "model_usage": dict(sorted(model_usage.items())),
            "light_model_call_count": light_model_call_count,
            "light_model_total_tokens": light_model_total_tokens,
            "heavy_model_call_count": total_calls - light_model_call_count,
            "heavy_model_total_tokens": total_tokens - light_model_total_tokens,
            "light_task_call_count": light_task_call_count,
            "light_task_total_tokens": light_task_total_tokens,
            "heavy_task_call_count": total_calls - light_task_call_count,
            "heavy_task_total_tokens": total_tokens - light_task_total_tokens,
            "model_mix_ratio": self._ratio_map(tokens_by_model, total_tokens),
            "task_type_mix_ratio": self._ratio_map(tokens_by_task_type, total_tokens),
        }

    def _filter_records(
        self,
        *,
        build_session_id: str | None,
        subject_id: str | None,
        workflow: str | None,
        lane: str | None,
        node: str | None,
    ) -> list[LLMCallRecord]:
        return [
            record
            for record in self._records
            if (build_session_id is None or record.build_session_id == build_session_id)
            and (subject_id is None or record.subject_id == subject_id)
            and (workflow is None or record.workflow == workflow)
            and (lane is None or record.lane == lane)
            and (node is None or record.node == node)
        ]

    @staticmethod
    def _ratio_map(values: dict[str, int], total: int) -> dict[str, float]:
        if total <= 0:
            return {}
        return {
            key: round((value / total), 4)
            for key, value in sorted(values.items(), key=lambda item: (-item[1], item[0]))
            if value > 0
        }

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "total_calls": 0,
            "failed_call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": 0.0,
            "tokens_by_model": {},
            "tokens_by_task_type": {},
            "tokens_by_lane": {},
            "tokens_by_node": {},
            "call_count_by_model": {},
            "call_count_by_task_type": {},
            "call_count_by_lane": {},
            "call_count_by_node": {},
            "model_usage": {},
            "light_model_call_count": 0,
            "light_model_total_tokens": 0,
            "heavy_model_call_count": 0,
            "heavy_model_total_tokens": 0,
            "light_task_call_count": 0,
            "light_task_total_tokens": 0,
            "heavy_task_call_count": 0,
            "heavy_task_total_tokens": 0,
            "model_mix_ratio": {},
            "task_type_mix_ratio": {},
        }


_tracker: LLMCallTracker | None = None


def get_tracker() -> LLMCallTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMCallTracker()
    return _tracker


__all__ = [
    "LLMCallRecord",
    "LLMCallTracker",
    "get_tracker",
]
