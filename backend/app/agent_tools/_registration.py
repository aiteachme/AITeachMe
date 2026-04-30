"""Registration helpers for project-owned agent tool modules."""

from __future__ import annotations

import importlib
from types import ModuleType

from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import get_tool_registry


def register_tool_definitions_from_modules(module_names: tuple[str, ...]) -> None:
    """Import modules and re-register decorated tool definitions."""

    for module_name in module_names:
        module = importlib.import_module(module_name)
        _register_module_tool_definitions(module)


def _register_module_tool_definitions(module: ModuleType) -> None:
    registry = get_tool_registry()
    seen: set[int] = set()
    for value in vars(module).values():
        definition = getattr(value, "__tool_definition__", None)
        if not isinstance(definition, ToolDefinition):
            continue
        key = id(definition)
        if key in seen:
            continue
        seen.add(key)
        if registry.get(definition.name) is definition:
            continue
        registry.register(definition)
