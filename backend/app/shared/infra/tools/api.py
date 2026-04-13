"""Public API for registered callable tools."""

from __future__ import annotations

import structlog

from app.shared.infra.tools.tool_loader import load_external_toolpacks
from app.shared.infra.tools.registry import get_tool_registry

logger = structlog.get_logger(__name__)

_PROJECT_TOOL_MODULES = (
    "app.shared.infra.tools.builtin.memory_ops",
    "app.shared.infra.tools.builtin.search_kb",
    "app.shared.infra.tools.builtin.web_search",
    "app.teaching.tools",
)
_project_tool_modules_loaded = False


def _sync_project_owned_registrations() -> None:
    try:
        from app.teaching.teaching import sync_teaching_tool_registry

        sync_teaching_tool_registry()
    except Exception as exc:  # pragma: no cover - defensive sync path
        logger.warning("project_tool_registry_sync_failed", error=str(exc))


def ensure_project_tool_modules_loaded() -> None:
    global _project_tool_modules_loaded
    if _project_tool_modules_loaded:
        _sync_project_owned_registrations()
        return

    import importlib

    for module_name in _PROJECT_TOOL_MODULES:
        try:
            importlib.import_module(module_name)
            logger.debug("project_tool_module_imported", module=module_name)
        except Exception as exc:
            logger.warning("project_tool_module_import_failed", module=module_name, error=str(exc))
    load_external_toolpacks()
    _project_tool_modules_loaded = True
    _sync_project_owned_registrations()


def list_agent_tools() -> list[dict[str, object]]:
    ensure_project_tool_modules_loaded()
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "tags": list(definition.tags),
            "source": definition.source,
        }
        for definition in get_tool_registry().list_all()
    ]


async def run_agent_tool(name: str, **kwargs):
    ensure_project_tool_modules_loaded()
    return await get_tool_registry().execute(name, **kwargs)


__all__ = [
    "ensure_project_tool_modules_loaded",
    "list_agent_tools",
    "run_agent_tool",
]
