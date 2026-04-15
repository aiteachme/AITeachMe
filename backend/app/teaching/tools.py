"""Legacy compatibility facade for canonical teaching-tool implementations."""

from app.workflows.support.teaching_tools import (
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
