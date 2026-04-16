"""State for the ingest fast-parse chain."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.ingest.common.parsing.classifier import ClassificationResult
from app.workflows.ingest.common.parsing.strategy import ParsePlan


class IngestParseState(TypedDict, total=False):
    """Phase 1 (Fast Parse) workflow state."""

    subject: str
    file_id: int
    filename: str
    filetype: str
    file_path: str
    markdown_path: str
    asset_dir: str
    asset_name_prefix: str
    content_hash: str | None
    file_size_bytes: int | None
    classification: ClassificationResult | None
    classification_payload: str | None
    estimated_pages: int | None
    detected_language: str | None
    parse_plan: ParsePlan | None
    parse_plan_payload: str | None
    parse_metadata: str | None
    parsed_markdown: str | None
    parser_used: str | None
    attempted_parsers: list[str]
    parser_elapsed_s: dict[str, float]
    markdown_chars: int
    image_count: int
    rewritten_image_refs: int
    extracted_data_images: int
    appended_asset_images: int
    error: str | None


__all__ = ["IngestParseState"]


