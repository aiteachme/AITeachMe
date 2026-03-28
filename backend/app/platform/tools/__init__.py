"""工具注册与调用。"""
from app.platform.tools.definition import ToolDefinition
from app.platform.tools.registry import ToolRegistry, get_tool_registry
from app.platform.tools.decorator import tool
__all__ = ["ToolDefinition", "ToolRegistry", "get_tool_registry", "tool"]
