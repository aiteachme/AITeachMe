"""Legacy compatibility exports for historical teaching imports."""

from . import skill_tools as _skill_tools
from . import tools as _tools
from .teaching import list_teaching_functions, run_teaching_function, teaching_function

__all__ = [
    "_skill_tools",
    "_tools",
    "list_teaching_functions",
    "run_teaching_function",
    "teaching_function",
]
