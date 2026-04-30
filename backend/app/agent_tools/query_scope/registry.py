"""Registration for query-scope agent tools."""

from __future__ import annotations

from app.agent_tools._registration import register_tool_definitions_from_modules

_MODULES = (
    "app.agent_tools.query_scope.knowledge",
    "app.agent_tools.query_scope.memory",
    "app.agent_tools.query_scope.system",
    "app.agent_tools.query_scope.web",
)


def register_agent_tools() -> None:
    register_tool_definitions_from_modules(_MODULES)


__all__ = ["register_agent_tools"]
