"""Pydantic models for digest observability."""

from __future__ import annotations

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
    """Unified digest timing and token report."""

    status: str = "completed"
    elapsed_ms: int = 0
    unified: dict[str, Any] = Field(default_factory=dict)
    docgen: dict[str, Any] = Field(default_factory=dict)
    kg: dict[str, Any] = Field(default_factory=dict)
    curriculum: dict[str, Any] = Field(default_factory=dict)
    llm: DigestTokenSummary = Field(default_factory=DigestTokenSummary)
    top_slowest_steps: list[SlowItemTiming] = Field(default_factory=list)
