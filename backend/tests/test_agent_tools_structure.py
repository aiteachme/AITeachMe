from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.agent_tools.context import AgentToolContext
from app.agent_tools.global_scope.ask_user import ask_user_options_tool
from app.agent_tools.policy import AgentToolPolicyRequest, resolve_agent_tool_names
from app.agent_tools.registry import register_agent_tools
from app.shared.infra.agent_loop import (
    AgentLoopConfig,
    StreamingToolCall,
    _execute_one_tool,
    _tool_stream_override_kwargs,
    _tool_stream_override_kwargs_with_choice,
)
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.tooling import resolve_interact_tool_plan, synthesize_ask_user_options_action


def test_agent_tool_registry_loads_scoped_tools(monkeypatch) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)

    register_agent_tools()

    names = {definition.name for definition in registry.list_all()}
    assert {"search_kb", "web_search", "recall_info", "remember_info", "ask_user_options"}.issubset(names)


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
    ) == ["search_kb", "ask_user_options"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(scene="web_research", course_id="course_123")
    ) == ["web_search", "recall_info", "search_kb", "ask_user_options"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(source="home_intake", course_id="global")
    ) == ["web_search", "recall_info", "ask_user_options"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(source="home_intake", course_id="global", allow_write_tools=True)
    ) == ["web_search", "recall_info", "ask_user_options"]
    assert resolve_agent_tool_names(
        AgentToolPolicyRequest(
            source="home_intake",
            course_id="global",
            allow_write_tools=True,
            approved_tool_names=frozenset({"remember_info"}),
        )
    ) == ["web_search", "recall_info", "ask_user_options", "remember_info"]


def test_interact_tool_plan_forces_ask_user_options_when_requested() -> None:
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.SINGLE_PASS,
        course_id="course_123",
        retrieval_results=[],
        scene="course_chat",
        source="course_chat",
        question="使用 ask_user_options 问我问题",
    )

    assert plan.tool_names == ["ask_user_options"]
    assert plan.forced_tool_name == "ask_user_options"

    home_plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.SINGLE_PASS,
        course_id="global",
        retrieval_results=[],
        scene="home_intake",
        source="home_intake",
        question="使用ask_user_options问我问题",
    )

    assert home_plan.tool_names == ["ask_user_options"]
    assert home_plan.forced_tool_name == "ask_user_options"


def test_synthesizes_ask_user_options_action_from_numbered_text() -> None:
    actions = synthesize_ask_user_options_action(
        question="使用ask_user_options问我问题",
        assistant_response=(
            "请选择一个方向：\n\n"
            "1. 基础概念\n"
            "2. 实战练习\n"
            "3. 复习计划"
        ),
    )

    assert actions == [
        {
            "type": "ask_user_options",
            "payload": {
                "question": "请选择一个方向：",
                "options": [
                    {"id": "option_1", "label": "基础概念", "value": "基础概念", "description": ""},
                    {"id": "option_2", "label": "实战练习", "value": "实战练习", "description": ""},
                    {"id": "option_3", "label": "复习计划", "value": "复习计划", "description": ""},
                ],
                "allow_custom_response": True,
            },
        }
    ]


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

    streamed = asyncio.run(
        _execute_one_tool(
            registry,
            StreamingToolCall(
                id="call_2",
                type="function",
                function_name="write_test",
                arguments=json.dumps({"value": "stream"}),
            ),
            AgentLoopConfig(
                tool_context=AgentToolContext(
                    user_id="user_a",
                    approved_tool_names=frozenset({"write_test"}),
                ),
            ),
        )
    )
    assert streamed.success
    assert streamed.result == "stream:user_a"


def test_ask_user_options_tool_returns_client_action() -> None:
    result = asyncio.run(
        ask_user_options_tool(
            question="Choose a path",
            options=[
                {"label": "Start with basics", "value": "basics"},
                {"label": "Take a quiz", "value": "quiz", "description": "Check current level"},
            ],
        )
    )

    assert result["ok"] is True
    assert result["client_actions"] == [
        {
            "type": "ask_user_options",
            "payload": {
                "question": "Choose a path",
                "options": [
                    {
                        "id": "option_1",
                        "label": "Start with basics",
                        "value": "basics",
                        "description": "",
                    },
                    {
                        "id": "option_2",
                        "label": "Take a quiz",
                        "value": "quiz",
                        "description": "Check current level",
                    },
                ],
                "allow_custom_response": True,
            },
        }
    ]


def test_agent_loop_extracts_tool_client_actions() -> None:
    async def handler() -> dict[str, object]:
        return {
            "ok": True,
            "client_actions": [
                {
                    "type": "ask_user_options",
                    "payload": {"question": "Pick one", "options": []},
                }
            ],
        }

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="action_test",
            description="test action tool",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=handler,
            is_async=True,
        )
    )
    tool_call = SimpleNamespace(
        id="call_action",
        function=SimpleNamespace(name="action_test", arguments=json.dumps({})),
    )
    collected: list[dict[str, object]] = []

    async def collect(actions, metadata):  # noqa: ANN001
        collected.extend(actions)
        assert metadata["tool_name"] == "action_test"

    record = asyncio.run(
        _execute_one_tool(
            registry,
            tool_call,
            AgentLoopConfig(client_action_handler=collect),
        )
    )

    assert record.success
    assert record.client_actions == collected
    assert collected[0]["type"] == "ask_user_options"


def test_streaming_tool_loop_disables_parallel_tool_calls() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    kwargs = _tool_stream_override_kwargs(tools)

    assert kwargs["stream"] is True
    assert kwargs["tools"] is tools
    assert kwargs["parallel_tool_calls"] is False

    forced_kwargs = _tool_stream_override_kwargs_with_choice(tools, "ask_user_options")
    assert forced_kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "ask_user_options"},
    }
