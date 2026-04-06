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
    graph_job_id: int
    curriculum_job_id: int
    shared_inputs: SharedInputs
    materialized: MaterializedSections

    # Per-lane outputs — fully independent
    doc_state: dict[str, Any]
    kg_state: dict[str, Any]
    curriculum_state: dict[str, Any]

    # Lane status flags
    graph_ready: bool
    doc_lane_error: str | None
    kg_lane_error: str | None

    # Timing
    shared_prepare_ms: int
    lane_ms: int
    parallel_lanes_ms: int
    doc_lane_ms: int
    kg_lane_ms: int
    curriculum_ms: int
    publish_ms: int
    cleanup_ms: int
    timing_report: dict[str, Any]
    token_summary: dict[str, Any]
    error: str | None


class UnifiedBuildResult(BaseModel):
    """Public result returned by the unified digest runtime."""

    subject: str
    build_session_id: str
    success: bool
    error: str | None = None
    doc_count: int = 0
    doc_ids: list[int] = Field(default_factory=list)
    chunk_count: int = 0
    new_node_count: int = 0
    new_edge_count: int = 0
    curriculum_ready: bool = False
    elapsed_ms: int = 0
    shared_prepare_ms: int = 0
    doc_lane_ms: int = 0
    kg_lane_ms: int = 0
    curriculum_ms: int = 0
    timing_report: dict[str, Any] | None = None
    token_summary: dict[str, Any] | None = None
