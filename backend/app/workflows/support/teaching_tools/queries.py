"""Query helpers for canonical teaching tools."""

from __future__ import annotations

from app.shared.infra.tools.teaching_registry import (
    list_teaching_functions,
    run_teaching_function,
)


def list_registered_teaching_tools() -> list[dict[str, object]]:
    """Return the registered teaching-tool catalog."""

    return list_teaching_functions()


__all__ = [
    "list_registered_teaching_tools",
    "list_teaching_functions",
    "run_teaching_function",
]
