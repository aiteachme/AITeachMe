"""State for the ingest deep-enhance chain."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.ingest.parsing.classifier import ClassificationResult
from app.workflows.ingest.parsing.strategy import ParsePlan


class IngestEnhanceState(TypedDict, total=False):
    """Phase 2 (Deep Enhance) workflow state."""

    subject: str
    file_id: int
    file_path: str
    filetype: str
    markdown_path: str
    asset_dir: str
    asset_name_prefix: str
    classification: ClassificationResult | None
    parse_plan: ParsePlan | None
    asset_ocr_images: int
    asset_ocr_replacements: int
    enhanced_markdown: str | None
    error: str | None


__all__ = ["IngestEnhanceState"]

