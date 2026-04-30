"""Registration for course-scope agent tools."""

from __future__ import annotations

from app.agent_tools._registration import register_tool_definitions_from_modules

_MODULES = (
    "app.agent_tools.course_scope.build",
    "app.agent_tools.course_scope.editing",
    "app.agent_tools.course_scope.files",
    "app.agent_tools.course_scope.learning",
)


def register_agent_tools() -> None:
    register_tool_definitions_from_modules(_MODULES)


__all__ = ["register_agent_tools"]
