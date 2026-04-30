"""Unified registration entrypoint for project-owned agent tools."""

from __future__ import annotations

import importlib

_SCOPE_REGISTRY_MODULES = (
    "app.agent_tools.global_scope.registry",
    "app.agent_tools.course_scope.registry",
    "app.agent_tools.query_scope.registry",
    "app.agent_tools.authoring_scope.registry",
)


def register_agent_tools() -> None:
    """Register all project-owned agent tools into the shared registry."""

    for module_name in _SCOPE_REGISTRY_MODULES:
        module = importlib.import_module(module_name)
        register_scope_tools = getattr(module, "register_agent_tools")
        register_scope_tools()


def _register_sync_hook_once() -> None:
    try:
        from app.shared.infra.tools.api import register_tool_registry_sync_hook
    except Exception:
        return
    register_tool_registry_sync_hook(register_agent_tools)


_register_sync_hook_once()
register_agent_tools()

__all__ = ["register_agent_tools"]
