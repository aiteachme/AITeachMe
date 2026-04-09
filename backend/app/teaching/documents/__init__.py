"""Teaching-specific helpers for learning-document generation."""

from .content_blocks import (
    build_glossary_section,
    build_learning_objectives_section,
)
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
    "build_glossary_section",
    "build_learning_objectives_section",
    "ensure_chapter_learning_scaffold",
]
