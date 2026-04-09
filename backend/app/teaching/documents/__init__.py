"""Teaching-specific helpers for learning-document generation."""

from .content_blocks import (
    build_glossary_section,
    build_learning_objectives_section,
)
from .report_generation import (
    build_chapter_title_resolution_messages,
    build_chapter_guide,
    build_chapter_recap,
    build_document_overview,
    clean_generated_chapter_title,
    coerce_resolved_chapter_title,
    ensure_chapter_learning_scaffold,
    is_usable_resolved_chapter_title,
    looks_like_legacy_template_title,
    resolve_effective_chapter_title,
)

__all__ = [
    "build_chapter_title_resolution_messages",
    "build_chapter_guide",
    "build_chapter_recap",
    "build_document_overview",
    "build_glossary_section",
    "build_learning_objectives_section",
    "clean_generated_chapter_title",
    "coerce_resolved_chapter_title",
    "ensure_chapter_learning_scaffold",
    "is_usable_resolved_chapter_title",
    "looks_like_legacy_template_title",
    "resolve_effective_chapter_title",
]
