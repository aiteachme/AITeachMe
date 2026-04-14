"""Shared context builders for the examine workflow.

This module is a backward-compatible re-export facade.  The actual
implementation is split across focused submodules:

- ``context_helpers``  – Small shared helpers (truncation, normalization, etc.)
- ``style_profile``    – ExamStyleProfile, TemplateSelectionHints, style building
- ``unit_context``     – NodeExamContext, UnitExamContext, batch DB loaders
- ``grading_context``  – Grading knowledge context builder
"""

from __future__ import annotations

# ── Re-exports from context_helpers ──────────────────────────────────
from app.workflows.examine.context_helpers import (
    build_template_context_signature,
    has_explicit_exam_context,
    normalize_difficulty_focus,
    read_knowledge_doc_text,
    summarize_hint_text,
    truncate_text,
)

# ── Re-exports from style_profile ────────────────────────────────────
from app.workflows.examine.style_profile import (
    ExamStyleProfile,
    TemplateSelectionHints,
    build_exam_style_profile,
    load_template_selection_hints,
    template_matches_request_context,
)

# ── Re-exports from unit_context ─────────────────────────────────────
from app.workflows.examine.unit_context import (
    NodeExamContext,
    UnitExamContext,
    build_unit_exam_contexts,
)

# ── Re-exports from grading_context ──────────────────────────────────
from app.workflows.examine.grading_context import (
    build_grading_knowledge_context,
)

__all__ = [
    "ExamStyleProfile",
    "NodeExamContext",
    "TemplateSelectionHints",
    "UnitExamContext",
    "build_template_context_signature",
    "build_exam_style_profile",
    "build_grading_knowledge_context",
    "build_unit_exam_contexts",
    "has_explicit_exam_context",
    "load_template_selection_hints",
    "normalize_difficulty_focus",
    "read_knowledge_doc_text",
    "summarize_hint_text",
    "template_matches_request_context",
    "truncate_text",
]
