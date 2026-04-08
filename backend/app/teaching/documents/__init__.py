"""Teaching-specific helpers for learning-document generation."""

from .report_generation import (
    build_chapter_guide,
    build_chapter_recap,
    build_document_overview,
    ensure_chapter_learning_scaffold,
)

__all__ = [
    "build_chapter_guide",
    "build_chapter_recap",
    "build_document_overview",
    "ensure_chapter_learning_scaffold",
]
