"""Typed state for the rewritten DocGen lane."""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict


class DocGenState(TypedDict, total=False):
    """State carried by the DocGen graph."""

    subject: str
    file_ids: list[int]
    user_prompt: str | None
    requested_at: datetime
    build_session_id: str
    planner_session_id: str
    confirmed_plan_id: str
    confirmed_plan: dict[str, Any] | None
    digest_mode: str
    course_type: str
    retrieval_profile: str
    teaching_action: str
    shared_inputs: Any
    raw_chunks: list[dict[str, Any]]
    subject_profile: dict[str, Any] | None
    document_context: dict[str, Any] | None
    docgen_context: dict[str, Any]

    chapter_assignments: list[dict[str, Any]]
    enhanced_chapter_outlines: list[dict[str, Any]]
    intent_profile: dict[str, Any]
    file_summaries: list[dict[str, Any]]
    source_affinity_by_chapter: list[dict[str, Any]]
    high_confidence_evidence_units: list[dict[str, Any]]
    plan_mismatch_warnings: list[str]
    chapter_generation_plan_seed: dict[str, Any]
    chapter_task_seeds: list[dict[str, Any]]
    backbone_research_agenda: dict[str, Any]
    document_backbone: dict[str, Any]
    backbone_conflict_warnings: list[dict[str, Any]]
    chapter_generation_plan: dict[str, Any]
    chapter_tasks: list[dict[str, Any]]
    chapter_task: dict[str, Any]
    total_chapters: int

    chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    enhanced_chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    reviewed_chapter_drafts: list[dict[str, Any]]
    research_traces: Annotated[list[dict[str, Any]], operator.add]
    evidence_ledgers: Annotated[list[dict[str, Any]], operator.add]
    claim_ledgers: Annotated[list[dict[str, Any]], operator.add]
    claim_evidence_maps: Annotated[list[dict[str, Any]], operator.add]
    conflict_reports: Annotated[list[dict[str, Any]], operator.add]
    asset_manifests: Annotated[list[dict[str, Any]], operator.add]
    practice_manifests: Annotated[list[dict[str, Any]], operator.add]
    research_sources: Annotated[list[str], operator.add]
    chapter_review_reports: list[dict[str, Any]]
    document_consistency_report: dict[str, Any]
    review_actions: list[dict[str, Any]]
    unresolved_warnings: list[str]

    final_chapter_titles: list[dict[str, Any]]
    title_review_report: dict[str, Any]
    chapter_metadatas: list[dict[str, Any]]
    merge_review_report: dict[str, Any]
    merged_markdown: str
    enriched_markdown: str
    merged_path: str
    doc_ids: list[int]
    built_paths: list[tuple[int, str]]

    load_ms: int
    prepare_ms: Annotated[int, operator.add]
    dispatch_ms: int
    backbone_ms: int
    research_ms: Annotated[int, operator.add]
    draft_ms: Annotated[int, operator.add]
    enhance_ms: Annotated[int, operator.add]
    review_ms: int
    repair_ms: int
    merge_review_ms: int
    finalize_ms: int
    llm_calls_total: Annotated[int, operator.add]
    llm_calls_skipped: Annotated[int, operator.add]
    timing_summary: dict[str, Any]
    token_summary: dict[str, Any]
    error: str | None


__all__ = ["DocGenState"]
