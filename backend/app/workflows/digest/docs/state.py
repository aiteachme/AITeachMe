"""DocGen workflow state."""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict


class DocGenState(TypedDict, total=False):
    """State for the knowledge docs generation workflow."""

    subject: str
    file_ids: list[int]
    user_prompt: str | None
    requested_at: datetime

    raw_chunks: list[dict[str, Any]]
    clean_chunks: list[dict[str, Any]]
    local_outlines: list[dict[str, Any]]
    outline_tree: dict[str, Any]
    chapter_assignments: list[dict[str, Any]]

    chapter_drafts: Annotated[list[dict[str, Any]], operator.add]
    chapter_reviews: Annotated[list[dict[str, Any]], operator.add]
    chapter_metadatas: Annotated[list[dict[str, Any]], operator.add]
    draft_ms: Annotated[int, operator.add]
    review_ms: Annotated[int, operator.add]
    metadata_ms: Annotated[int, operator.add]
    llm_calls_total: Annotated[int, operator.add]
    llm_calls_skipped: Annotated[int, operator.add]

    doc_ids: list[int]
    merged_markdown: str
    merged_path: str
    load_ms: int
    cleanse_ms: int
    outline_ms: Annotated[int, operator.add]
    finalize_ms: int
    error: str | None


__all__ = ["DocGenState"]
