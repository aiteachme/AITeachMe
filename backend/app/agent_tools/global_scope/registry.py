"""Registration for global-scope agent tools."""

from __future__ import annotations

from app.agent_tools._registration import register_tool_definitions_from_modules

_MODULES = (
    "app.agent_tools.global_scope.ask_user",
    "app.agent_tools.global_scope.course_management",
    "app.agent_tools.global_scope.memory",
    "app.agent_tools.global_scope.plan_management",
    "app.agent_tools.global_scope.skill_management",
)


def register_agent_tools() -> None:
    register_tool_definitions_from_modules(_MODULES)


__all__ = ["register_agent_tools"]
