"""DocGen graph state contract.

这里集中描述 LangGraph 节点之间传递的 state 字段，包括 Send fan-out
临时字段、reducer 聚合字段和最终发布字段。HTTP schema / DB model 不在
这里定义。
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict


class DocGenState(TypedDict, total=False):
    """State carried by the DocGen graph."""

    course_id: str
    course_name: str
    user_id: str
    file_ids: list[str]
    user_prompt: str | None
    requested_at: datetime
    build_session_id: str
    planner_session_id: str
    confirmed_plan_id: str
    confirmed_plan: dict[str, Any] | None
    digest_mode: str
    model_override: str | None
    retrieval_profile: str
    retrieval_policy: dict[str, Any]
    teaching_action: str
    shared_inputs: Any
    raw_chunks: list[dict[str, Any]]
    course_profile: dict[str, Any] | None
    learner_profile_context: dict[str, Any]
    learner_profile_text: str
    user_profile: dict[str, Any]
    document_context: dict[str, Any] | None
    docgen_context: dict[str, Any]

    chapter_assignments: list[dict[str, Any]]
    chapter_assignment: dict[str, Any]
    intent_core: dict[str, Any]
    intent_profile: dict[str, Any]
    intent_enhanced: dict[str, Any]
    locked_title_items: Annotated[list[dict[str, Any]], operator.add]
    locked_titles: list[dict[str, Any]]
    file_summaries: list[dict[str, Any]]
    summary_enhanced: dict[str, Any]
    source_affinity_by_chapter: list[dict[str, Any]]
    high_confidence_evidence_units: list[dict[str, Any]]
    plan_mismatch_warnings: list[str]
    chapter_generation_plan_seed: dict[str, Any]
    chapter_task_seeds: list[dict[str, Any]]
    chapters_enhanced: list[dict[str, Any]]
    preliminary_kg: dict[str, Any]
    chapter_task_seed: dict[str, Any]
    backbone_research_agenda: dict[str, Any]
    document_backbone: dict[str, Any]
    guideline: dict[str, Any]
    backbone_conflict_warnings: list[dict[str, Any]]
    chapter_execution_brief_items: Annotated[list[dict[str, Any]], operator.add]
    chapter_execution_briefs: list[dict[str, Any]]
    chapter_generation_plan: dict[str, Any]
    dispatch_table: dict[str, Any]
    chapter_tasks: list[dict[str, Any]]
    chapter_task: dict[str, Any]
    enhanced_chapter_draft: dict[str, Any]
    review_chapter_task: dict[str, Any]
    review_claim_ledger: dict[str, Any]
    review_claim_evidence_map: dict[str, Any]
    review_conflict_report: dict[str, Any]
    total_chapters: int

    chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    enhanced_chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    reviewed_chapter_draft_items: Annotated[list[dict[str, Any]], operator.add]
    reviewed_chapter_overlay_items: Annotated[list[dict[str, Any]], operator.add]
    chapter_review_report_items: Annotated[list[dict[str, Any]], operator.add]
    review_action_items: Annotated[list[dict[str, Any]], operator.add]
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
    review_decision: str
    review_actions: list[dict[str, Any]]
    unresolved_warnings: list[str]
    repair_loop_state: dict[str, Any]
    repair_trace: Annotated[list[dict[str, Any]], operator.add]

    final_chapter_titles: list[dict[str, Any]]
    title_review_report: dict[str, Any]
    cover_artifact: dict[str, Any]
    cover_markdown: str
    chapter_metadatas: list[dict[str, Any]]
    merge_review_report: dict[str, Any]
    merged_markdown: str
    enriched_markdown: str
    merged_path: str
    doc_ids: list[int]
    built_paths: list[tuple[int, str]]
    build_group_id: str
    graph_sync_status: str
    graph_sync_metrics: dict[str, Any]

    load_ms: int
    prepare_ms: Annotated[int, operator.add]
    cover_ms: int
    intent_core_ms: int
    title_lock_ms: Annotated[int, operator.add]
    seed_backbone_ms: int
    backbone_ms: int
    chapter_prepare_ms: Annotated[int, operator.add]
    assemble_tasks_ms: int
    research_ms: Annotated[int, operator.add]
    draft_ms: Annotated[int, operator.add]
    enhance_ms: Annotated[int, operator.add]
    review_ms: Annotated[int, operator.add]
    repair_ms: int
    merge_review_ms: int
    finalize_ms: int
    graph_sync_ms: int
    file_summary_llm_calls: Annotated[int, operator.add]
    llm_calls_total: Annotated[int, operator.add]
    llm_calls_skipped: Annotated[int, operator.add]
    timing_summary: dict[str, Any]
    token_summary: dict[str, Any]
    error: str | None


__all__ = ["DocGenState"]
