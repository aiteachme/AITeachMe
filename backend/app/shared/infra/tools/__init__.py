"""工具注册与调用。"""
from app.shared.infra.tools.api import (
    ensure_project_tool_modules_loaded,
    list_agent_tools,
    register_tool_registry_sync_hook,
    run_agent_tool,
)
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry, get_tool_registry
from app.shared.infra.tools.decorator import tool
from app.shared.infra.tools.teaching_registry import (
    list_teaching_functions,
    run_teaching_function,
    teaching_function,
)
from app.shared.infra.tools.tool_loader import load_external_toolpacks, load_toolpack_manifests
__all__ = [
    "ToolDefinition",
    "ToolRegistry",
    "ensure_project_tool_modules_loaded",
    "get_tool_registry",
    "load_external_toolpacks",
    "list_agent_tools",
    "load_toolpack_manifests",
    "register_tool_registry_sync_hook",
    "run_agent_tool",
    "list_teaching_functions",
    "run_teaching_function",
    "teaching_function",
    "tool",
]
