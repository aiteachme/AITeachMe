"""Shared metrics helpers for digest workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field


class SlowItemTiming(BaseModel):
    """A single slow item entry."""

    item_id: str
    title: str = ""
    elapsed_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DigestModelUsageSummary(BaseModel):
    """Model-level token usage summary."""

    call_count: int = 0
    failed_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0


class DigestTokenSummary(BaseModel):
    """Token summary for a workflow build or lane."""

    total_calls: int = 0
    failed_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    avg_latency_ms: float = 0.0
    tokens_by_model: dict[str, int] = Field(default_factory=dict)
    tokens_by_task_type: dict[str, int] = Field(default_factory=dict)
    tokens_by_lane: dict[str, int] = Field(default_factory=dict)
    tokens_by_node: dict[str, int] = Field(default_factory=dict)
    call_count_by_model: dict[str, int] = Field(default_factory=dict)
    call_count_by_task_type: dict[str, int] = Field(default_factory=dict)
    call_count_by_lane: dict[str, int] = Field(default_factory=dict)
    call_count_by_node: dict[str, int] = Field(default_factory=dict)
    model_usage: dict[str, DigestModelUsageSummary] = Field(default_factory=dict)
    light_model_call_count: int = 0
    light_model_total_tokens: int = 0
    heavy_model_call_count: int = 0
    heavy_model_total_tokens: int = 0
    light_task_call_count: int = 0
    light_task_total_tokens: int = 0
    heavy_task_call_count: int = 0
    heavy_task_total_tokens: int = 0
    model_mix_ratio: dict[str, float] = Field(default_factory=dict)
    task_type_mix_ratio: dict[str, float] = Field(default_factory=dict)


class DigestTimingReport(BaseModel):
    """Digest timing and token report."""

    status: str = "completed"
    elapsed_ms: int = 0
    overall: dict[str, Any] = Field(default_factory=dict)
    docgen: dict[str, Any] = Field(default_factory=dict)
    knowledge: dict[str, Any] = Field(default_factory=dict)
    llm: DigestTokenSummary = Field(default_factory=DigestTokenSummary)
    top_slowest_steps: list[SlowItemTiming] = Field(default_factory=list)


def build_token_summary(
    *,
    build_session_id: str | None = None,
    subject: str | None = None,
    workflow: str | None = None,
    lane: str | None = None,
    node: str | None = None,
) -> DigestTokenSummary:
    """Build a typed token summary from the shared LLM tracker."""

    from app.shared.infra.config import get_settings
    from app.shared.infra.observability.llm_stats import get_tracker

    if not get_settings().digest_token_summary_enabled:
        return DigestTokenSummary()
    raw_summary = get_tracker().get_summary(
        build_session_id=build_session_id,
        subject=subject,
        workflow=workflow,
        lane=lane,
        node=node,
    )
    return DigestTokenSummary.model_validate(raw_summary)


def build_slow_items(
    items: Sequence[Mapping[str, Any] | SlowItemTiming],
    *,
    top_k: int | None = None,
) -> list[SlowItemTiming]:
    """Normalize and trim slow item records."""

    limit = _top_k(top_k)
    normalized: list[SlowItemTiming] = []
    for item in items:
        if isinstance(item, SlowItemTiming):
            normalized.append(item)
            continue
        normalized.append(
            SlowItemTiming(
                item_id=str(
                    item.get("item_id")
                    or item.get("chunk_id")
                    or item.get("chapter_index")
                    or item.get("title")
                    or "item"
                ),
                title=str(item.get("title") or item.get("name") or item.get("chunk_title") or ""),
                elapsed_ms=int(item.get("elapsed_ms", 0)),
                metadata={
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "item_id",
                        "title",
                        "name",
                        "chunk_id",
                        "chapter_index",
                        "chunk_title",
                        "elapsed_ms",
                    }
                },
            )
        )
    normalized.sort(key=lambda entry: (-entry.elapsed_ms, entry.item_id))
    return normalized[:limit]


def add_slow_item(
    items: list[dict[str, Any]],
    *,
    item_id: str,
    title: str,
    elapsed_ms: int,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append a slow item and keep only the slowest top-k entries."""

    items.append(
        {
            "item_id": item_id,
            "title": title,
            "elapsed_ms": int(elapsed_ms),
            **(metadata or {}),
        }
    )
    items.sort(key=lambda item: (-int(item.get("elapsed_ms", 0)), str(item.get("item_id", ""))))
    del items[_top_k() :]
    return items


def step_slow_items(step_map: Mapping[str, int], *, top_k: int | None = None) -> list[SlowItemTiming]:
    """Turn a simple step->elapsed map into ranked slow items."""

    return build_slow_items(
        [
            {"item_id": step_name, "title": step_name, "elapsed_ms": elapsed_ms}
            for step_name, elapsed_ms in step_map.items()
            if int(elapsed_ms) > 0
        ],
        top_k=top_k,
    )


def build_lane_step_slow_items(lane: str, step_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Turn lane step timings into normalized slow-item dictionaries."""

    items: list[dict[str, Any]] = []
    for step_name, elapsed_ms in step_map.items():
        elapsed = int(elapsed_ms or 0)
        if elapsed <= 0:
            continue
        items.append(
            {
                "item_id": f"{lane}.{step_name}",
                "title": f"{lane}.{step_name}",
                "elapsed_ms": elapsed,
                "lane": lane,
                "step": step_name,
            }
        )
    return items


def build_lane_llm_rollup(token_summary: DigestTokenSummary) -> dict[str, Any]:
    """Create the common lane-level LLM metrics payload."""

    return {
        "llm_total_calls": token_summary.total_calls,
        "failed_llm_call_count": token_summary.failed_call_count,
        "llm_total_latency_ms": token_summary.total_latency_ms,
        "llm_avg_latency_ms": token_summary.avg_latency_ms,
        "tokens_by_model": token_summary.tokens_by_model,
        "tokens_by_task_type": token_summary.tokens_by_task_type,
        "call_count_by_model": token_summary.call_count_by_model,
        "call_count_by_task_type": token_summary.call_count_by_task_type,
        "light_vs_heavy_model_mix": {
            "light_model_call_count": token_summary.light_model_call_count,
            "light_model_total_tokens": token_summary.light_model_total_tokens,
            "heavy_model_call_count": token_summary.heavy_model_call_count,
            "heavy_model_total_tokens": token_summary.heavy_model_total_tokens,
        },
        "task_type_mix_ratio": token_summary.task_type_mix_ratio,
        "model_mix_ratio": token_summary.model_mix_ratio,
    }


def _top_k(value: int | None = None) -> int:
    from app.shared.infra.config import get_settings

    if value is not None:
        return max(1, int(value))
    return max(1, int(get_settings().digest_timing_top_k))


__all__ = [
    "DigestModelUsageSummary",
    "DigestTimingReport",
    "DigestTokenSummary",
    "SlowItemTiming",
    "add_slow_item",
    "build_lane_llm_rollup",
    "build_lane_step_slow_items",
    "build_slow_items",
    "build_token_summary",
    "step_slow_items",
]
