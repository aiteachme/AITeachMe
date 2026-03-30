"""Digest curriculum workflow state types."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


class CurriculumDeriveState(TypedDict, total=False):
    subject: str
    build_session_id: str
    graph_job_id: int
    curriculum_job_id: int
    impact_set: ImpactSet | None
    derived_unit_ids: list[int]
    created_unit_ids: list[int]
    updated_unit_ids: list[int]
    theme_tree_version_id: int | None
    prereq_dag_version_id: int | None
    snapshot_id: int | None
    curriculum_version_no: int | None
    curriculum_ready: bool
    derive_units_ms: int
    theme_tree_ms: int
    prereq_dag_ms: int
    finalize_ms: int
    subgraph_load_ms: int
    candidate_build_ms: int
    unit_naming_ms: int
    unit_persist_ms: int
    rule_named_unit_count: int
    llm_named_unit_count: int
    fallback_named_unit_count: int
    unit_naming_parallelism: int
    slowest_unit_namings: list[dict[str, object]]
    timing_summary: dict[str, object]
    token_summary: dict[str, object]
    error: str | None


__all__ = ["CurriculumDeriveState"]
