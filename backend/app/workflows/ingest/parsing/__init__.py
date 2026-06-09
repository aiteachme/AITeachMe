"""Ingest parsing package."""

from __future__ import annotations

from app.workflows.ingest.parsing.decision import (
    DEFAULT_MARKITDOWN_EXTENSIONS,
    DEFAULT_MINERU_EXTENSIONS,
    DEFAULT_PADDLE_OCR_EXTENSIONS,
    build_markitdown_capability,
    build_mineru_capability,
    build_paddle_ocr_capability,
    build_parse_decision,
)
from app.workflows.ingest.parsing.lib.provider_contracts import (
    ParseDecision,
    ProviderCapability,
)

__all__ = [
    "DEFAULT_MINERU_EXTENSIONS",
    "DEFAULT_PADDLE_OCR_EXTENSIONS",
    "DEFAULT_MARKITDOWN_EXTENSIONS",
    "ParseDecision",
    "ProviderCapability",
    "build_markitdown_capability",
    "build_mineru_capability",
    "build_paddle_ocr_capability",
    "build_parse_decision",
]
