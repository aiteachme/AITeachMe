from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.agent_tools.context import AgentToolContext
from app.agent_tools.policy import AgentToolPolicyRequest, resolve_agent_tool_names
from app.agent_tools.registry import register_agent_tools
from app.shared.infra.agent_loop import AgentLoopConfig, _execute_one_tool
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry


def test_agent_tool_registry_loads_scoped_tools(monkeypatch) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)

    register_agent_tools()

    names = {definition.name for definition in registry.list_all()}
    assert {"search_kb", "web_search", "recall_info", "remember_info"}.issubset(names)


def test_hidden_args_are_not_exposed_to_model_schema(monkeypatch) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)

    register_agent_tools()

    definition = registry.get("search_kb")
    assert definition is not None
    assert definition.hidden_args == ["course_id"]

    parameters = definition.to_openai_format()["function"]["parameters"]
    assert "course_id" not in parameters["properties"]
    assert "course_id" not in parameters["required"]


def test_agent_tool_policy_scopes_tools_by_context() -> None:
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(course_id="course_123")
    ) == ["search_kb"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(scene="web_research", course_id="course_123")
    ) == ["web_search", "recall_info", "search_kb"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(source="home_intake", course_id="global")
    ) == ["web_search", "recall_info"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(source="home_intake", course_id="global", allow_write_tools=True)
    ) == ["web_search", "recall_info"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(
            source="home_intake",
            course_id="global",
            allow_write_tools=True,
            approved_tool_names=frozenset({"remember_info"}),
        )
    ) == ["web_search", "recall_info", "remember_info"]


def test_agent_loop_injects_hidden_args_and_requires_approval() -> None:
    async def handler(value: str, user_id: str | None = None) -> str:
        return f"{value}:{user_id}"

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write_test",
            description="test write tool",
            parameters={
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "user_id": {"type": "string"},
                },
                "required": ["value", "user_id"],
            },
            handler=handler,
            is_async=True,
            requires_approval=True,
            hidden_args=["user_id"],
        )
    )
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="write_test",
            arguments=json.dumps({"value": "ok"}),
        ),
    )

    denied = asyncio.run(
        _execute_one_tool(
            registry,
            tool_call,
            AgentLoopConfig(tool_context=AgentToolContext(user_id="user_a")),
        )
    )
    assert not denied.success

    allowed = asyncio.run(
        _execute_one_tool(
            registry,
            tool_call,
            AgentLoopConfig(
                tool_context=AgentToolContext(
                    user_id="user_a",
                    approved_tool_names=frozenset({"write_test"}),
                ),
            ),
        )
    )
    assert allowed.success
    assert allowed.result == "ok:user_a"
    assert allowed.arguments["user_id"] == "user_a"
