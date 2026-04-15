"""Canonical teaching-tool package."""

from app.workflows.support.teaching_tools import commands as _commands
from app.workflows.support.teaching_tools.commands import (
    compare_concepts,
    explain_formula,
    generate_similar_problems,
    solve_step_by_step,
)
from app.workflows.support.teaching_tools.queries import (
    list_registered_teaching_tools,
    list_teaching_functions,
    run_teaching_function,
)

__all__ = [
    "_commands",
    "compare_concepts",
    "explain_formula",
    "generate_similar_problems",
    "list_registered_teaching_tools",
    "list_teaching_functions",
    "run_teaching_function",
    "solve_step_by_step",
]
