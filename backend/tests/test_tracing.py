from __future__ import annotations

import asyncio

import pytest
from langsmith import traceable

from app.shared.infra import agent_loop as agent_loop_module
from app.shared.infra import llm_support as llm_module
from app.shared.infra.settings import Settings, get_settings
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability.llm_stats import LLMCallRecord, LLMCallTracker
from app.shared.infra.observability.trace import (
    build_langsmith_tags,
    get_llm_trace_context,
    langsmith_capture_inputs_enabled,
    langsmith_capture_outputs_enabled,
    normalize_langsmith_run_type,
)
from app.shared.infra.observability import llm_stats as llm_stats_module
from app.shared.infra.observability import trace as trace_module
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry
from app.shared.infra.execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.shared.infra.execution.units import _traced_execution_outputs
from app.shared.infra.tools import registry as registry_module
from app.shared.infra.workflow import emit_progress, workflow_tracer
from app.shared.infra.workflow.context import LANGGRAPH_DEV_SUBJECT, WorkflowContext
from app.workflows.digest.docgen.lib import DocGenWriterRuntime


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_langsmith_inputs_redact_messages_when_capture_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_CAPTURE_INPUTS", "false")

    inputs = llm_module._langsmith_inputs(
        call_model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "secret prompt"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "extract_outline",
                    "description": "sensitive tool description",
                },
            }
        ],
    )

    assert inputs["model"] == "openai/gpt-4o-mini"
    assert inputs["messages"][0]["role"] == "user"
    assert inputs["messages"][0]["content"] == "[redacted]"
    assert inputs["tools"][0]["function"]["name"] == "extract_outline"
    assert inputs["tools"][0]["function"]["description"] == "[redacted]"


def test_langsmith_outputs_include_usage_metadata(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_CAPTURE_OUTPUTS", "false")

    outputs = llm_module._langsmith_outputs(
        text="secret answer",
        result={"status": "ok"},
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
    )

    assert outputs["choices"][0]["message"]["content"] == "[redacted]"
    assert outputs["usage_metadata"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert outputs["result_type"] == "dict"


def test_langsmith_trace_kwargs_include_invocation_metadata(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_CAPTURE_INPUTS", "true")

    trace_kwargs = llm_module._langsmith_trace_kwargs(
        task_type=TaskType.CHAT,
        call_model="openai/gpt-4o-mini",
        provider="openai",
        model_name="gpt-4o-mini",
        mode="text",
        messages=[{"role": "user", "content": "hello"}],
        call_kwargs={
            "temperature": 0.25,
            "max_tokens": 256,
            "stop": ["END"],
            "response_format": {"type": "json_object"},
        },
        attempt=2,
    )

    metadata = trace_kwargs["extra_metadata"]

    assert metadata["ls_provider"] == "openai"
    assert metadata["ls_model_name"] == "gpt-4o-mini"
    assert metadata["ls_model_type"] == "chat"
    assert metadata["ls_temperature"] == 0.25
    assert metadata["ls_max_tokens"] == 256
    assert metadata["ls_stop"] == ["END"]
    assert metadata["ls_invocation_params"]["response_format"] == {"type": "json_object"}


def test_langsmith_value_redacts_data_urls() -> None:
    value = llm_module._sanitize_langsmith_value(
        {"image_url": "data:image/png;base64,abcd"},
        capture_text=True,
    )

    assert value["image_url"] == "[redacted:data-url:image/png]"


def test_langsmith_capture_defaults_to_enabled_in_local_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.delenv("LANGSMITH_CAPTURE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_CAPTURE_OUTPUTS", raising=False)

    assert langsmith_capture_inputs_enabled() is True
    assert langsmith_capture_outputs_enabled() is True


def test_langsmith_capture_defaults_to_disabled_in_cloud_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "cloud")
    monkeypatch.delenv("LANGSMITH_CAPTURE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_CAPTURE_OUTPUTS", raising=False)

    assert langsmith_capture_inputs_enabled() is False
    assert langsmith_capture_outputs_enabled() is False


def test_langsmith_capture_respects_explicit_config_flags(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("LANGSMITH_CAPTURE_INPUTS", "false")
    monkeypatch.setenv("LANGSMITH_CAPTURE_OUTPUTS", "true")

    assert langsmith_capture_inputs_enabled() is False
    assert langsmith_capture_outputs_enabled() is True


def test_llm_call_tracker_trims_old_records(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_stats_module,
        "get_settings",
        lambda: Settings(observability={"llm_observability_max_records": 2}),
    )
    tracker = LLMCallTracker()

    tracker.record(LLMCallRecord(task_type="chat", model="model-1", call_id="call-1"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-2", call_id="call-2"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-3", call_id="call-3"))

    assert [record.call_id for record in tracker._records] == ["call-2", "call-3"]


def test_langsmith_tracing_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        trace_module,
        "get_settings",
        lambda: Settings(observability={"tracing_enabled": True}),
    )
    monkeypatch.setattr(trace_module, "_langsmith_endpoint_reachable", lambda: True)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    assert trace_module.langsmith_tracing_enabled() is False

    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")

    assert trace_module.langsmith_tracing_enabled() is True


def test_base_runtime_run_sets_nested_llm_trace_scope() -> None:
    class DummyTracedExecution(BaseTracedExecution):
        async def execute(self, **kwargs) -> TracedExecutionResult:
            del kwargs
            trace = get_llm_trace_context()
            return TracedExecutionResult(
                metadata={
                    "trace_workflow": trace.workflow,
                    "trace_lane": trace.lane,
                    "trace_node": trace.node,
                }
            )

    context = TracedExecutionContext(
        subject="demo",
        build_session_id="build-1",
        workflow_context=WorkflowContext(
            workflow_name="digest.docgen.test",
            subject=LANGGRAPH_DEV_SUBJECT,
            metadata={"lane": "docgen"},
        ),
        digest_mode="sprint",
        chapter_index=2,
    )
    result = asyncio.run(DummyTracedExecution(context).run())

    assert result.metadata["trace_workflow"] == "digest.docgen.test"
    assert result.metadata["trace_lane"] == "docgen"
    assert result.metadata["trace_node"] == "traced_execution.DummyTracedExecution"


def test_docgen_writer_runtime_uses_workflow_runtime_trace_namespace() -> None:
    captured: dict[str, str] = {}

    async def fake_llm(*_args, **_kwargs) -> str:
        trace = get_llm_trace_context()
        captured["workflow"] = trace.workflow
        captured["lane"] = trace.lane
        captured["node"] = trace.node
        return "# 偏导数\n\n正文"

    context = TracedExecutionContext(
        subject="demo",
        build_session_id="build-2",
        workflow_context=WorkflowContext(
            workflow_name="digest.docgen.test",
            subject=LANGGRAPH_DEV_SUBJECT,
            metadata={"lane": "docgen"},
        ),
        chapter_index=1,
        llm_caller=fake_llm,
    )
    asyncio.run(
        DocGenWriterRuntime(context).run(
            chapter_plan={"chapter_index": 1, "title": "偏导数"},
            dense_context="偏导数是多元函数沿坐标方向的变化率。",
            tone="encouraging",
            digest_mode="systematic",
        )
    )

    assert captured["workflow"] == "digest.docgen.test"
    assert captured["lane"] == "docgen"
    assert captured["node"] == "workflow_runtime.docgen.writer"


def test_traced_execution_outputs_include_cache_and_retrieval_profile_fields() -> None:
    outputs = _traced_execution_outputs(
        TracedExecutionResult(
            content="dense context",
            sources=["https://example.com/math"],
            metadata={
                "cache_status": "hit",
                "cache_hit": True,
                "stop_reason": "coverage_target_met",
                "requested_profile": "docgen_systematic",
                "applied_profile": "docgen_systematic",
                "requested_retrieval_profile": "docgen_systematic",
                "applied_retrieval_profile": "docgen_systematic",
            },
        )
    )

    assert outputs["cache_status"] == "hit"
    assert outputs["cache_hit"] is True
    assert outputs["stop_reason"] == "coverage_target_met"
    assert outputs["requested_profile"] == "docgen_systematic"
    assert outputs["applied_profile"] == "docgen_systematic"
    assert outputs["requested_retrieval_profile"] == "docgen_systematic"
    assert outputs["applied_retrieval_profile"] == "docgen_systematic"



def test_workflow_tracer_wraps_node() -> None:
    async def handler(_state):
        return {"ok": True}

    trace = workflow_tracer(workflow="digest.planner", lane="planner")
    wrapped = trace.node(handler, name="bound_node")

    result = asyncio.run(wrapped({"subject": "demo"}))

    assert result == {"ok": True}


def test_workflow_tracer_requires_handler_argument() -> None:
    trace = workflow_tracer(workflow="digest.planner", lane="planner")

    with pytest.raises(TypeError, match="requires a handler argument"):
        trace.node(None, name="decorated_node")


def test_workflow_tracer_keeps_result_thin() -> None:
    async def handler(_state):
        return {"ok": True}

    trace = workflow_tracer(workflow="digest.planner", lane="planner")
    wrapped = trace.node(handler, name="test_node")
    result = asyncio.run(
        wrapped(
            {
                "subject": "demo",
                "node_events": [{"name": "legacy"}],
                "node_timings_ms": {"legacy": 1},
            }
        )
    )

    assert result == {"ok": True}
    assert "node_events" not in result
    assert "node_timings_ms" not in result


def test_workflow_tracer_applies_timing_field() -> None:
    async def handler(_state):
        return {"ok": True}

    trace = workflow_tracer(workflow="digest.planner", lane="planner")
    wrapped = trace.node(handler, name="timed_node", timing_field="timed_ms")
    result = asyncio.run(wrapped({"subject": "demo"}))

    assert result["ok"] is True
    assert isinstance(result["timed_ms"], int)
    assert result["timed_ms"] >= 0


def test_official_traceable_prompt_function_runs() -> None:
    @traceable(name="prompt_builder", run_type="prompt")
    def build_prompt(subject: str) -> str:
        return f"teach {subject}"

    assert build_prompt("math") == "teach math"


def test_emit_progress_compact_payload() -> None:
    payloads: list[dict[str, str]] = []

    async def callback(payload):
        payloads.append(payload)

    state = {"progress_callback": callback}

    asyncio.run(
        emit_progress(
            state,
            stage="planner",
            step="load_context",
            detail="已读取资料。",
            elapsed_ms=12,
        )
    )

    assert payloads == [
        {
            "stage": "planner",
            "step": "load_context",
            "detail": "已读取资料。",
            "elapsed_ms": 12,
        }
    ]


def test_normalize_langsmith_run_type_falls_back_to_tool() -> None:
    assert normalize_langsmith_run_type("prompt") == "prompt"
    assert normalize_langsmith_run_type("retriever") == "retriever"
    assert normalize_langsmith_run_type("not-a-run-type") == "tool"


def test_langsmith_tags_stay_sparse() -> None:
    tags = build_langsmith_tags(
        workflow="digest.docgen",
        lane="docgen",
        node="research_chapters",
        extra_tags=["task:docgen", "task:docgen"],
    )

    assert tags == ["aiteachme", "workflow:digest.docgen", "lane:docgen", "task:docgen"]
    assert "node:research_chapters" not in tags


def test_tool_registry_traced_runner_builds_tool_trace_payload() -> None:
    registry = ToolRegistry()

    async def demo_tool(query: str) -> dict[str, str]:
        return {"result": f"handled:{query}"}

    definition = ToolDefinition(
        name="demo_tool",
        description="demo",
        parameters={"type": "object"},
        handler=demo_tool,
        is_async=True,
        tags=["retrieval"],
        source="python",
    )
    registry.register(definition)

    payload = asyncio.run(
        registry._run_traced_tool(
            tool_name="demo_tool",
            arguments={"query": "线性代数"},
            tool_definition=definition,
        )
    )
    result = asyncio.run(registry.execute("demo_tool", query="线性代数"))

    assert payload["result"] == {"result": "handled:线性代数"}
    assert payload["trace"] == {
        "success": True,
        "result_keys": ["result"],
        "result_type": "dict",
    }
    assert result == {"result": "handled:线性代数"}

    assert registry_module._tool_trace_inputs(
        {
            "tool_name": "demo_tool",
            "arguments": {"query": "线性代数"},
        }
    ) == {
        "name": "demo_tool",
        "arguments": {"query": "线性代数"},
    }

    assert registry_module._tool_trace_metadata(
        registry,
        tool_name="demo_tool",
        arguments={"query": "线性代数"},
        tool_definition=definition,
    ) == {
        "tool_name": "demo_tool",
        "tool_source": "python",
        "tool_tags": ["retrieval"],
        "tool_is_async": True,
    }
    assert registry_module._tool_trace_tags(
        registry,
        tool_name="demo_tool",
        arguments={"query": "线性代数"},
        tool_definition=definition,
    ) == ["tool:demo_tool", "tool_tag:retrieval"]
    assert registry_module._tool_trace_outputs({"trace": payload["trace"]}) == payload["trace"]


def test_run_agent_loop_loads_project_tools_before_registry_lookup(monkeypatch) -> None:
    calls: list[str] = []

    class DummyRegistry:
        def to_openai_format(self):
            calls.append("registry")
            return []

    async def fake_acompletion(messages, *, task_type, **kwargs):
        del messages, task_type, kwargs
        return "ok"

    monkeypatch.setattr("app.shared.infra.tools.api.ensure_project_tool_modules_loaded", lambda: calls.append("load"))
    monkeypatch.setattr("app.shared.infra.tools.registry.get_tool_registry", lambda: DummyRegistry())
    monkeypatch.setattr("app.shared.infra.llm_support.acompletion", fake_acompletion)

    result = asyncio.run(
        agent_loop_module.run_agent_loop(
            [{"role": "user", "content": "hello"}],
        )
    )

    assert result.final_answer == "ok"
    assert calls[:2] == ["load", "registry"]


def test_run_agent_loop_injects_tool_argument_overrides(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class DummyRegistry:
        def to_openai_format(self):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "search_kb",
                        "description": "demo",
                        "parameters": {"type": "object"},
                    },
                }
            ]

        async def execute(self, name: str, **kwargs):
            calls.append({"name": name, "kwargs": kwargs})
            return {"result": "知识片段"}

    class FakeToolFunction:
        name = "search_kb"
        arguments = '{"query":"偏导数"}'

    class FakeToolCall:
        id = "tool-1"
        function = FakeToolFunction()

    class FakeToolMessage:
        content = None
        tool_calls = [FakeToolCall()]

    class FakeFinalMessage:
        content = "最终回答"
        tool_calls = None

    class FakeResponse:
        def __init__(self, message):
            self.choices = [type("Choice", (), {"message": message})()]

    responses = iter(
        [
            FakeResponse(FakeToolMessage()),
            FakeResponse(FakeFinalMessage()),
        ]
    )

    async def fake_acompletion_with_tools(messages, *, tools, task_type, **kwargs):
        del messages, tools, task_type, kwargs
        return next(responses)

    monkeypatch.setattr("app.shared.infra.tools.api.ensure_project_tool_modules_loaded", lambda: None)
    monkeypatch.setattr("app.shared.infra.tools.registry.get_tool_registry", lambda: DummyRegistry())
    monkeypatch.setattr("app.shared.infra.llm_support.acompletion_with_tools", fake_acompletion_with_tools)

    result = asyncio.run(
        agent_loop_module.run_agent_loop(
            [{"role": "user", "content": "帮我一步步理解偏导数"}],
            tools=["search_kb"],
            config=agent_loop_module.AgentLoopConfig(
                max_iterations=2,
                tool_argument_overrides={"search_kb": {"subject": "math_demo"}},
            ),
        )
    )

    assert result.final_answer == "最终回答"
    assert calls == [
        {
            "name": "search_kb",
            "kwargs": {"query": "偏导数", "subject": "math_demo"},
        }
    ]
