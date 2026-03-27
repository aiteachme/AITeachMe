"""MCP (Model Context Protocol) 客户端 — 标准化外部工具接入。

MCP 是 Anthropic 提出的标准协议，用于让 LLM 安全地访问外部数据源和工具。
支持 OpenHands / Dify / Claude 等主流系统。

对外使用::

    from app.core.mcp import MCPManager, get_mcp_manager

    mgr = get_mcp_manager()
    await mgr.connect("sqlite", {"path": "/data/notes.db"})
    tools = mgr.list_tools()
    result = await mgr.call_tool("read_table", table="notes")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class MCPTool:
    """MCP 暴露的工具描述。"""

    name: str
    description: str
    parameters: dict
    server_name: str = ""


@dataclass
class MCPServer:
    """MCP 服务器连接信息。"""

    name: str
    transport: str           # "stdio" | "sse" | "streamable-http"
    config: dict[str, Any] = field(default_factory=dict)
    tools: list[MCPTool] = field(default_factory=list)
    connected: bool = False


class MCPManager:
    """MCP 连接管理器。

    管理多个 MCP 服务器连接，统一暴露工具。
    工具自动注册到 ToolRegistry，可被 Agent Loop 调用。
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}

    async def connect(
        self,
        name: str,
        config: dict[str, Any],
        transport: str = "stdio",
    ) -> bool:
        """连接一个 MCP 服务器。

        Args:
            name: 服务器名称。
            config: 连接配置（命令、环境变量等）。
            transport: 传输方式。

        Returns:
            是否连接成功。

        Example::

            await mgr.connect("filesystem", {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
            })
        """

        server = MCPServer(name=name, transport=transport, config=config)

        try:
            # 尝试使用 mcp 库
            tools = await self._discover_tools(server)
            server.tools = tools
            server.connected = True
            self._servers[name] = server

            # 注册到 ToolRegistry
            self._register_to_tools(server)

            logger.info("mcp_server_connected",
                        name=name, tool_count=len(tools))
            return True
        except Exception as exc:
            logger.warning("mcp_connection_failed",
                           name=name, error=str(exc))
            return False

    async def disconnect(self, name: str) -> None:
        """断开 MCP 服务器。"""
        if name in self._servers:
            del self._servers[name]
            logger.info("mcp_server_disconnected", name=name)

    def list_tools(self) -> list[MCPTool]:
        """列出所有已连接服务器的工具。"""
        tools = []
        for server in self._servers.values():
            if server.connected:
                tools.extend(server.tools)
        return tools

    def list_servers(self) -> list[dict]:
        """列出所有已连接服务器。"""
        return [
            {
                "name": s.name,
                "transport": s.transport,
                "connected": s.connected,
                "tool_count": len(s.tools),
            }
            for s in self._servers.values()
        ]

    async def call_tool(
        self,
        tool_name: str,
        **kwargs,
    ) -> str:
        """调用 MCP 工具。

        Args:
            tool_name: 工具名称。
            **kwargs: 工具参数。

        Returns:
            工具执行结果（字符串）。
        """

        for server in self._servers.values():
            for tool in server.tools:
                if tool.name == tool_name:
                    return await self._execute_tool(server, tool_name, kwargs)

        raise ValueError(f"MCP 工具 `{tool_name}` 未找到")

    async def _discover_tools(self, server: MCPServer) -> list[MCPTool]:
        """发现 MCP 服务器提供的工具。"""

        try:
            # 尝试使用 mcp 官方库
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=server.config.get("command", ""),
                args=server.config.get("args", []),
                env=server.config.get("env"),
            )

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        MCPTool(
                            name=t.name,
                            description=t.description or "",
                            parameters=t.inputSchema or {},
                            server_name=server.name,
                        )
                        for t in result.tools
                    ]
        except ImportError:
            logger.info("mcp_library_not_installed",
                        hint="pip install mcp 可启用完整 MCP 支持")
            return []

    async def _execute_tool(
        self,
        server: MCPServer,
        tool_name: str,
        args: dict,
    ) -> str:
        """通过 MCP 协议执行工具。"""

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=server.config.get("command", ""),
                args=server.config.get("args", []),
                env=server.config.get("env"),
            )

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=args)
                    return str(result.content[0].text if result.content else "")
        except ImportError:
            return f"MCP 库未安装，无法执行工具 `{tool_name}`"

    def _register_to_tools(self, server: MCPServer) -> None:
        """将 MCP 工具注册到 ToolRegistry。"""

        try:
            from app.core.tools.registry import get_tool_registry
            from app.core.tools.definition import ToolDefinition

            registry = get_tool_registry()
            for tool in server.tools:
                async def _make_handler(tn=tool.name):
                    async def handler(**kwargs):
                        return await self.call_tool(tn, **kwargs)
                    return handler

                td = ToolDefinition(
                    name=f"mcp_{tool.name}",
                    description=f"[MCP:{server.name}] {tool.description}",
                    parameters=tool.parameters,
                    handler=None,  # MCP 工具通过 call_tool 调用
                    is_async=True,
                )
                registry.register(td)
        except Exception as exc:
            logger.debug("mcp_tool_registration_skipped", error=str(exc))


# ── 全局单例 ──────────────────────────────────────────────────

_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    """返回全局 MCP 管理器单例。"""
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
