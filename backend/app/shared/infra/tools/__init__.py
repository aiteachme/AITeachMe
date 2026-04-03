"""工具注册与调用。"""
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry, get_tool_registry
from app.shared.infra.tools.decorator import tool
__all__ = ["ToolDefinition", "ToolRegistry", "get_tool_registry", "tool"]
