"""Legacy compatibility facade for the canonical teaching registry."""

from app.shared.infra.tools.teaching_registry import (
    list_teaching_functions,
    run_teaching_function,
    sync_teaching_tool_registry,
    teaching_function,
)

__all__ = [
    "list_teaching_functions",
    "run_teaching_function",
    "sync_teaching_tool_registry",
    "teaching_function",
]
