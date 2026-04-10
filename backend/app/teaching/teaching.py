"""Teaching-facing catalog over canonical tool registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.shared.infra.tools import (
    ensure_project_tool_modules_loaded,
    get_tool_registry,
    run_agent_tool,
    tool,
)

_CATEGORY_TAG_PREFIX = "teaching_category:"


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
    return tool(name=name, description=description, tags=deduped_tags, source="teaching")


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
    definition = get_tool_registry().get(name)
    if definition is None or (definition.source != "teaching" and "teaching" not in definition.tags):
        available = [item["name"] for item in list_teaching_functions()]
        raise ValueError(f"???? `{name}` ???????{available}")
    return await run_agent_tool(name, **kwargs)


__all__ = [
    "list_teaching_functions",
    "run_teaching_function",
    "teaching_function",
]
