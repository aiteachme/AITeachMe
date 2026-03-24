"""Unified build state and result models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.workflows.digest.build.models import CoverageReport
from app.workflows.digest.shared.models import SharedInputs


class UnifiedBuildState(BaseModel):
    """Internal coordination state for the unified digest build."""

    subject: str
    file_ids: list[int]
    user_prompt: str | None = None
    requested_at: datetime
    shared_inputs: SharedInputs | None = None

    # Keep runtime state schema lightweight so importing this module does not
    # require Pydantic to build schemas from TypedDict workflow states.
    doc_state: dict[str, Any] | None = None
    kg_state: dict[str, Any] | None = None

    chapter_priors_available: bool = False
    topic_snapshot_available: bool = False
    coverage_report: CoverageReport | None = None
    error: str | None = None


class UnifiedBuildResult(BaseModel):
    """Public result for the unified digest build."""

    subject: str
    success: bool
    error: str | None = None

    doc_count: int = 0
    doc_ids: list[int] = Field(default_factory=list)

    chunk_count: int = 0
    new_node_count: int = 0
    new_edge_count: int = 0

    coverage_report: CoverageReport | None = None
    repair_applied: bool = False

    elapsed_ms: int = 0
    shared_prepare_ms: int = 0
    doc_lane_ms: int = 0
    kg_lane_ms: int = 0
    consistency_check_ms: int = 0
