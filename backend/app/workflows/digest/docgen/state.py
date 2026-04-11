"""Typed state for the DocGen lane."""

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
    tone: str
    selected_skillpacks: list[str]
    shared_inputs: Any
    document_context: dict[str, Any] | None

    raw_chunks: list[dict[str, Any]]
    subject_profile: dict[str, Any] | None
    chapter_assignments: list[dict[str, Any]]
    chapter_materials: Annotated[list[dict[str, Any]], operator.add]
    research_sources: Annotated[list[str], operator.add]
    chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    chapter_metadatas: list[dict[str, Any]]
    exam_questions: list[dict[str, Any]]
    mermaid_block_count: int
    image_block_count: int
    interactive_block_count: int
    asset_count: int
    asset_summary: dict[str, int]
    practice_count: int

    merged_markdown: str
    enriched_markdown: str
    merged_path: str
    doc_ids: list[int]
    built_paths: list[tuple[int, str]]

    load_ms: int
    planner_ms: int
    research_ms: Annotated[int, operator.add]
    draft_ms: Annotated[int, operator.add]
    enrich_ms: int
    examine_ms: int
    finalize_ms: int
    llm_calls_total: Annotated[int, operator.add]
    llm_calls_skipped: Annotated[int, operator.add]
    timing_summary: dict[str, Any]
    token_summary: dict[str, Any]
    error: str | None
