"""State contracts for the ingest fast-parse lane.

这里定义 LangGraph 输入、运行时状态和输出字段。
状态既要覆盖上传后解析的 Phase 1 主链，也要承接 Phase 2 派发所需的最小信息。
"""

from __future__ import annotations

from typing import TypedDict

from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.provider_contracts import ParseDecision
from app.workflows.ingest.parsing.strategy import ParsePlan


class IngestParseGraphInput(TypedDict):
    """Graph input for one file parse run."""

    user_id: str
    subject: str
    file_id: int


class IngestParseGraphOutput(TypedDict, total=False):
    """Graph output surfaced to API-facing callers."""

    user_id: str
    subject: str
    file_id: int
    filename: str
    filetype: str
    parser_used: str | None
    parse_plan: ParsePlan | None
    needs_enhance: bool
    error: str | None


class IngestParseState(TypedDict, total=False):
    """Phase 1 (Fast Parse) workflow state."""

    user_id: str
    subject: str
    file_id: int
    filename: str
    filetype: str
    file_path: str
    temp_dir: str
    local_markdown_path: str
    local_asset_dir: str
    record_markdown_path: str
    record_asset_dir: str
    asset_upload_prefix: str
    asset_storage_dir: str
    asset_link_prefix: str
    asset_name_prefix: str
    storage_backend: str
    requested_parser_provider: str | None
    mineru_token: str | None
    mineru_token_source: str
    paddle_ocr_token: str | None
    paddle_ocr_token_source: str
    mineru_model_version: str
    mineru_enable_formula: bool
    mineru_enable_table: bool
    mineru_is_ocr: bool
    parse_decision: ParseDecision | None
    is_text_fast_path: bool
    text_category: str | None
    text_language_hint: str | None
    content_hash: str | None
    file_size_bytes: int | None
    classification: ClassificationResult | None
    classification_payload: str | None
    estimated_pages: int | None
    detected_language: str | None
    parse_plan: ParsePlan | None
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
    quality_score: float | None
    needs_enhance: bool
    needs_quality_reparse: bool
    needs_asset_ocr: bool
    load_ms: int
    fingerprint_ms: int
    classify_ms: int
    plan_ms: int
    parse_ms: int
    finalize_ms: int
    error: str | None


__all__ = [
    "IngestParseGraphInput",
    "IngestParseGraphOutput",
    "IngestParseState",
]
