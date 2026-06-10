from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

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
    run_agent_loop_stream,
)
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings import set_system_settings_override
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry
from app.workflows.common.model_policy import ProviderNativeToolPolicy
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib import model_policy as interact_model_policy
from app.workflows.interact.chat.lib.tooling import (
    build_interact_provider_native_tools,
    resolve_interact_tool_plan,
    synthesize_ask_user_options_action,
)
from app.workflows.interact.chat.lib.types import RetrievedContext


def teardown_function() -> None:
    set_system_settings_override({})


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


def test_interact_native_tools_request_web_search_for_global_assistant() -> None:
    set_system_settings_override({
        "llm": {
            "native_web_search": "auto",
            "native_web_search_external_access": False,
        }
    })
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.PLAN_EXECUTE,
        course_id="global",
        retrieval_results=[],
        scene="global_assistant",
        source="global_assistant",
        question="latest AI news",
    )

    assert "web_search" in plan.tool_names
    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="global",
    ) == [
        {"type": "web_search", "mode": "auto", "external_web_access": False},
    ]


def test_interact_native_tools_request_file_search_when_course_agent_lacks_local_context() -> None:
    set_system_settings_override({
        "llm": {
            "native_file_search": "auto",
            "native_file_search_vector_store_ids": "vs_course",
            "native_file_search_max_results": 3,
        }
    })
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.PLAN_EXECUTE,
        course_id="course-1",
        retrieval_results=[],
        scene="course_chat",
        source="quick_chat",
        question="explain chapter 1",
    )

    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="course-1",
        retrieval_results=[],
    ) == [
        {
            "type": "file_search",
            "mode": "auto",
            "vector_store_ids": ["vs_course"],
            "max_num_results": 3,
        },
    ]
    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="global",
        retrieval_results=[],
    ) == []


def test_interact_native_file_search_auto_does_not_shadow_strong_local_rag() -> None:
    set_system_settings_override({
        "llm": {
            "native_file_search": "auto",
            "native_file_search_vector_store_ids": "vs_course",
        }
    })
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.PLAN_EXECUTE,
        course_id="course-1",
        retrieval_results=[],
        scene="course_chat",
        source="quick_chat",
        question="explain chapter 1",
    )

    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="course-1",
        retrieval_results=[
            RetrievedContext(
                chunk_id=1,
                file_id="file-1",
                title="本地强证据",
                header_path="第一章",
                content="课程资料里的高相关解释。",
                score=0.86,
                low_relevance=False,
                retrieval_source="vector",
            )
        ],
    ) == []


def test_interact_native_file_search_auto_skips_plain_course_single_pass() -> None:
    set_system_settings_override({
        "llm": {
            "native_file_search": "auto",
            "native_file_search_vector_store_ids": "vs_course",
        }
    })
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.SINGLE_PASS,
        course_id="course-1",
        retrieval_results=[],
        scene="course_chat",
        source="quick_chat",
        question="explain chapter 1",
    )

    assert plan.tool_names == []
    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="course-1",
        retrieval_results=[],
    ) == []


def test_interact_native_file_search_force_can_override_local_gate() -> None:
    set_system_settings_override({
        "llm": {
            "native_file_search": "force",
            "native_file_search_vector_store_ids": "vs_course",
        }
    })
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.SINGLE_PASS,
        course_id="course-1",
        retrieval_results=[],
        scene="course_chat",
        source="quick_chat",
        question="explain chapter 1",
    )

    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="course-1",
        retrieval_results=[
            RetrievedContext(
                chunk_id=1,
                file_id="file-1",
                title="本地强证据",
                header_path="第一章",
                content="课程资料里的高相关解释。",
                score=0.86,
                low_relevance=False,
                retrieval_source="vector",
            )
        ],
    ) == [
        {
            "type": "file_search",
            "mode": "force",
            "vector_store_ids": ["vs_course"],
            "max_num_results": 5,
        },
    ]


def test_interact_native_tools_follow_step_model_policy(monkeypatch) -> None:
    set_system_settings_override({
        "llm": {
            "native_web_search": "force",
            "native_file_search": "force",
            "native_file_search_vector_store_ids": "vs_runtime",
        }
    })
    current_policy = interact_model_policy.get_interact_model_policy(
        interact_model_policy.InteractModelStep.RESPONSE_STREAM
    )
    monkeypatch.setitem(
        interact_model_policy._POLICIES,
        interact_model_policy.InteractModelStep.RESPONSE_STREAM,
        replace(current_policy, provider_native_tools=ProviderNativeToolPolicy.disabled()),
    )
    plan = resolve_interact_tool_plan(
        execution_mode=InteractExecutionMode.PLAN_EXECUTE,
        course_id="global",
        retrieval_results=[],
        scene="global_assistant",
        source="global_assistant",
        question="latest AI news",
    )

    assert "web_search" in plan.tool_names
    assert build_interact_provider_native_tools(
        tool_plan=plan,
        course_id="global",
    ) == []


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


def test_agent_loop_passes_tool_call_metadata_to_registry(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="trace_tool",
            description="trace tool",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "course_id": {"type": "string"},
                    "force_id": {"type": "string"},
                },
                "required": ["query", "course_id"],
            },
            handler=lambda query, course_id=None, force_id=None: "ok",
            hidden_args=["course_id"],
        )
    )
    captured: dict[str, object] = {}

    async def fake_execute(name, _approval_granted=False, _trace_metadata=None, **kwargs):  # noqa: ANN001
        captured["name"] = name
        captured["approval_granted"] = _approval_granted
        captured["trace_metadata"] = dict(_trace_metadata or {})
        captured["kwargs"] = dict(kwargs)
        return "ok"

    monkeypatch.setattr(registry, "execute", fake_execute)
    tool_call = SimpleNamespace(
        id="call_trace",
        function=SimpleNamespace(
            name="trace_tool",
            arguments=json.dumps({"query": "velocity"}),
        ),
    )

    record = asyncio.run(
        _execute_one_tool(
            registry,
            tool_call,
            AgentLoopConfig(
                tool_context=AgentToolContext(course_id="course_1"),
                tool_argument_overrides={"trace_tool": {"force_id": "force_1"}},
            ),
            tool_call_index=3,
        )
    )

    assert record.success
    assert captured["name"] == "trace_tool"
    assert captured["kwargs"] == {
        "query": "velocity",
        "course_id": "course_1",
        "force_id": "force_1",
    }
    metadata = captured["trace_metadata"]
    assert metadata["tool_call_id"] == "call_trace"
    assert metadata["tool_call_index"] == 3
    assert metadata["tool_visible_argument_names"] == ["query"]
    assert metadata["tool_context_argument_names"] == ["course_id"]
    assert metadata["tool_injected_argument_names"] == ["force_id"]
    assert metadata["tool_hidden_argument_names"] == ["course_id"]


def test_agent_loop_stream_falls_back_when_tool_stream_is_empty(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="noop_tool",
            description="noop",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda: "noop",
        )
    )

    class FakeEmptyToolStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=None, tool_calls=None),
                        ),
                    ],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    tool_calls: list[dict] = []
    fallback_calls: list[dict] = []

    class FakeLiteLLM:
        async def acompletion(self, **kwargs):
            tool_calls.append(kwargs)
            return FakeEmptyToolStream()

    async def fake_acompletion_stream(messages, **kwargs):
        fallback_calls.append({"messages": messages, **kwargs})
        yield "fallback answer"

    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)
    monkeypatch.setattr("app.shared.infra.tools.api.ensure_project_tool_modules_loaded", lambda: None)
    monkeypatch.setattr("app.shared.infra.llm_support.litellm_loader.load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr("app.shared.infra.llm_support.acompletion_stream", fake_acompletion_stream, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    async def collect_chunks() -> list[str]:
        return [
            chunk
            async for chunk in run_agent_loop_stream(
                [{"role": "user", "content": "hello"}],
                tools=["noop_tool"],
                config=AgentLoopConfig(
                    max_iterations=1,
                    task_type=TaskType.CHAT,
                    model="primary",
                ),
            )
        ]

    chunks = asyncio.run(collect_chunks())

    assert chunks == ["fallback answer"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tools"][0]["function"]["name"] == "noop_tool"
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["model"] == "primary"
    assert fallback_calls[0]["extra_metadata"]["agent_tool_stream_fallback"] == "empty_tool_response"


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


@pytest.mark.anyio
async def test_streaming_tool_loop_falls_back_before_first_token(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="noop_tool",
            description="noop",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda: "noop",
        )
    )

    class FakeChatStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="fallback ok")),
                    ],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    calls: list[dict] = []

    class FakeLiteLLM:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key":
                raise RuntimeError("primary tools stream down")
            return FakeChatStream()

    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)
    monkeypatch.setattr("app.shared.infra.tools.api.ensure_project_tool_modules_loaded", lambda: None)
    monkeypatch.setattr("app.shared.infra.llm_support.litellm_loader.load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "chat_completions"},
    })

    chunks = [
        chunk
        async for chunk in run_agent_loop_stream(
            [{"role": "user", "content": "hello"}],
            tools=["noop_tool"],
            config=AgentLoopConfig(
                max_iterations=1,
                task_type=TaskType.CHAT,
                model="primary",
            ),
        )
    ]

    assert chunks == ["fallback ok"]
    assert [call["api_key"] for call in calls] == ["primary-key", "fallback-key"]
    assert calls[1]["model"] == "deepseek-chat"


def test_streaming_tool_loop_does_not_leak_provider_native_tools(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="noop_tool",
            description="noop",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda: "noop",
        )
    )

    class EmptyToolStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    calls: list[dict] = []
    fallback_kwargs: list[dict] = []

    class FakeLiteLLM:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return EmptyToolStream()

    async def fake_acompletion_stream(messages, **kwargs):
        fallback_kwargs.append(kwargs)
        yield "fallback ok"

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr("app.shared.infra.tools.registry._registry", registry)
    monkeypatch.setattr("app.shared.infra.tools.api.ensure_project_tool_modules_loaded", lambda: None)
    monkeypatch.setattr("app.shared.infra.llm_support.litellm_loader.load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr("app.shared.infra.llm_support.acompletion_stream", fake_acompletion_stream, raising=False)
    set_system_settings_override({"llm": {"api_mode": "chat_completions"}})

    async def collect_chunks() -> list[str]:
        return [
            chunk
            async for chunk in run_agent_loop_stream(
                [{"role": "user", "content": "hello"}],
                tools=["noop_tool"],
                config=AgentLoopConfig(
                    max_iterations=1,
                    task_type=TaskType.CHAT,
                    model="primary",
                    llm_kwargs={
                        "provider_native_tools": [
                            {"type": "web_search", "mode": "auto"},
                        ],
                    },
                ),
            )
        ]

    chunks = asyncio.run(collect_chunks())

    assert chunks == ["fallback ok"]
    assert calls
    assert "provider_native_tools" not in calls[0]
    assert fallback_kwargs[0]["provider_native_tools"] == [
        {"type": "web_search", "mode": "auto"},
    ]
