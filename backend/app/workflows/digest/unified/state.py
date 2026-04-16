"""State and result models for unified digest builds."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from app.workflows.digest.shared.models import SharedInputs
from app.workflows.digest.unified.models import MaterializedSections


class UnifiedDigestState(TypedDict, total=False):
    """Top-level state carried across the unified build graph."""

    subject: str
    file_ids: list[int]
    user_prompt: str | None
    requested_at: datetime
    build_session_id: str
    planner_session_id: str
    confirmed_plan_id: str
    confirmed_plan: dict[str, Any] | None
    digest_mode: str
    tone: str
    graph_job_id: int
    shared_inputs: SharedInputs
    materialized: MaterializedSections

    doc_state: dict[str, Any]
    knowledge_state: dict[str, Any]

    graph_ready: bool
    doc_lane_error: str | None
    knowledge_lane_error: str | None

    shared_prepare_ms: int
    lane_ms: int
    parallel_lanes_ms: int
    doc_lane_ms: int
    knowledge_lane_ms: int
    publish_ms: int
    cleanup_ms: int
    timing_report: dict[str, Any]
    token_summary: dict[str, Any]
    error: str | None


class UnifiedBuildResult(BaseModel):
    """Public result returned by the unified digest runtime."""

    subject: str
    build_session_id: str
    planner_session_id: str | None = None
    confirmed_plan_id: str | None = None
    success: bool
    error: str | None = None
    doc_count: int = 0
    doc_ids: list[int] = Field(default_factory=list)
    chunk_count: int = 0
    new_node_count: int = 0
    new_edge_count: int = 0
    elapsed_ms: int = 0
    shared_prepare_ms: int = 0
    doc_lane_ms: int = 0
    knowledge_lane_ms: int = 0
    timing_report: dict[str, Any] | None = None
    token_summary: dict[str, Any] | None = None
