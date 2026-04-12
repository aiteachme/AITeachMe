"""Compatibility shim for historical teaching skill imports."""

from __future__ import annotations

from app.teaching.tools import (
    compare_concepts,
    explain_formula,
    generate_similar_problems,
    solve_step_by_step,
)

__all__ = [
    "compare_concepts",
    "explain_formula",
    "generate_similar_problems",
    "solve_step_by_step",
]
