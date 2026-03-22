"""Ingest workflow state."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.strategy import ParsePlan


class IngestParseState(TypedDict, total=False):
    subject: str
    file_id: int
    filename: str
    filetype: str
    file_path: str
    markdown_path: str
    asset_dir: str
    content_hash: str | None
    file_size_bytes: int | None
    classification: ClassificationResult | None
    classification_payload: str | None
    estimated_pages: int | None
    detected_language: str | None
    parse_plan: ParsePlan | None
    parse_plan_payload: str | None
    parse_metadata: str | None
    parser_used: str | None
    attempted_parsers: list[str]
    markdown_chars: int
    image_count: int
    error: str | None
