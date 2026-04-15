"""Canonical teaching-tool registry helpers.

This module is the long-term home for teaching-owned tool registration.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.shared.infra.tools.api import (
    ensure_project_tool_modules_loaded,
    register_tool_registry_sync_hook,
    run_agent_tool,
)
from app.shared.infra.tools.decorator import tool
from app.shared.infra.tools.registry import get_tool_registry

_CATEGORY_TAG_PREFIX = "teaching_category:"
_TEACHING_TOOL_CATALOG: dict[str, dict[str, Any]] = {}


def teaching_function(
    name: str,
    description: str,
    *,
    category: str = "general",
    tags: list[str] | None = None,
) -> Callable:
    """Register a teaching-owned callable function via the canonical tool registry."""

    resolved_tags = [
        "teaching",
        f"{_CATEGORY_TAG_PREFIX}{category}",
        *(tags or []),
    ]
    deduped_tags = list(dict.fromkeys(tag for tag in resolved_tags if str(tag).strip()))

    def decorator(func: Callable) -> Callable:
        registered = tool(name=name, description=description, tags=deduped_tags, source="teaching")(func)
        _TEACHING_TOOL_CATALOG[name] = {
            "name": name,
            "description": description,
            "tags": deduped_tags,
            "handler": registered,
        }
        return registered

    return decorator


def sync_teaching_tool_registry() -> None:
    """Re-register teaching-owned tools when the shared registry was recreated."""

    registry = get_tool_registry()
    for item in _TEACHING_TOOL_CATALOG.values():
        existing = registry.get(str(item["name"]))
        if existing is not None and (existing.source == "teaching" or "teaching" in existing.tags):
            continue
        tool(
            name=str(item["name"]),
            description=str(item["description"]),
            tags=list(item["tags"]),
            source="teaching",
        )(item["handler"])


register_tool_registry_sync_hook(sync_teaching_tool_registry)


def _resolve_category(tags: list[str]) -> str:
    for tag in tags:
        normalized = str(tag).strip()
        if normalized.startswith(_CATEGORY_TAG_PREFIX):
            category = normalized.removeprefix(_CATEGORY_TAG_PREFIX).strip()
            if category:
                return category
    return "general"


def _iter_teaching_tool_definitions():
    ensure_project_tool_modules_loaded()
    for definition in get_tool_registry().list_all():
        if definition.source == "teaching" or "teaching" in definition.tags:
            yield definition


def list_teaching_functions(category: str | None = None) -> list[dict[str, Any]]:
    """Return teaching-owned callable functions grouped by business category."""

    ensure_project_tool_modules_loaded()
    sync_teaching_tool_registry()
    items: list[dict[str, Any]] = []
    for definition in _iter_teaching_tool_definitions():
        resolved_category = _resolve_category(list(definition.tags))
        if category and resolved_category != category:
            continue
        items.append(
            {
                "name": definition.name,
                "description": definition.description,
                "category": resolved_category,
                "tags": list(definition.tags),
                "source": definition.source,
            }
        )
    return items


async def run_teaching_function(name: str, **kwargs: Any) -> Any:
    """Execute a teaching-owned callable function."""

    ensure_project_tool_modules_loaded()
    sync_teaching_tool_registry()
    definition = get_tool_registry().get(name)
    if definition is None or (definition.source != "teaching" and "teaching" not in definition.tags):
        available = [item["name"] for item in list_teaching_functions()]
        raise ValueError(f"未找到教学函数 `{name}`，当前可用函数有：{available}")
    return await run_agent_tool(name, **kwargs)


__all__ = [
    "list_teaching_functions",
    "run_teaching_function",
    "sync_teaching_tool_registry",
    "teaching_function",
]
