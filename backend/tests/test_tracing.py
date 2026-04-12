from __future__ import annotations

import asyncio

import pytest

from app.shared.infra import llm as llm_module
from app.shared.infra.config import Settings, get_settings
from app.shared.infra.llm_support import observability as llm_observability_module
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.traced_execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.shared.infra.tracing import (
    LLMCallRecord,
    LLMCallTracker,
    get_llm_trace_context,
    normalize_langsmith_run_type,
)
from app.shared.infra import tracing as tracing_module
from app.workflows.digest.docgen.runtime import DocGenWriterRuntime
from app.workflows.common import (
    node,
    traceable_run,
    wrap_node,
    wrap_traceable_run,
    workflow_node,
    wrap_workflow_node,
)
from app.workflows.common.context import LANGGRAPH_DEV_SUBJECT, WorkflowContext
from app.workflows.common import runtime_stats as runtime_stats_module
from app.workflows.common.runtime_stats import emit_progress, record_step_end, record_step_start, tracked_step


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_langsmith_inputs_redact_messages_when_capture_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_observability_module,
        "get_settings",
        lambda: Settings(_env_file=None, langsmith_capture_inputs=False),
    )

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
    monkeypatch.setattr(
        llm_observability_module,
        "get_settings",
        lambda: Settings(_env_file=None, langsmith_capture_outputs=False),
    )

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
    monkeypatch.setattr(
        llm_observability_module,
        "get_settings",
        lambda: Settings(_env_file=None, langsmith_capture_inputs=True),
    )

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


def test_langsmith_capture_defaults_to_enabled_in_local_mode() -> None:
    settings = Settings(
        _env_file=None,
        app_mode="local",
        langsmith_capture_inputs=None,
        langsmith_capture_outputs=None,
    )

    assert settings.resolved_langsmith_capture_inputs is True
    assert settings.resolved_langsmith_capture_outputs is True


def test_langsmith_capture_defaults_to_disabled_in_cloud_mode() -> None:
    settings = Settings(
        _env_file=None,
        app_mode="cloud",
        langsmith_capture_inputs=None,
        langsmith_capture_outputs=None,
    )

    assert settings.resolved_langsmith_capture_inputs is False
    assert settings.resolved_langsmith_capture_outputs is False


def test_langsmith_capture_respects_explicit_config_flags() -> None:
    settings = Settings(
        _env_file=None,
        app_mode="local",
        langsmith_capture_inputs=False,
        langsmith_capture_outputs=True,
    )

    assert settings.resolved_langsmith_capture_inputs is False
    assert settings.resolved_langsmith_capture_outputs is True


def test_llm_call_tracker_trims_old_records(monkeypatch) -> None:
    monkeypatch.setattr(
        tracing_module,
        "get_settings",
        lambda: Settings(_env_file=None, llm_observability_max_records=2),
    )
    tracker = LLMCallTracker()

    tracker.record(LLMCallRecord(task_type="chat", model="model-1", call_id="call-1"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-2", call_id="call-2"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-3", call_id="call-3"))

    assert [record.call_id for record in tracker._records] == ["call-2", "call-3"]


def test_langsmith_tracing_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        tracing_module,
        "get_settings",
        lambda: Settings(_env_file=None, tracing_enabled=True, langsmith_tracing=True),
    )
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    assert tracing_module.langsmith_tracing_enabled() is False

    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")

    assert tracing_module.langsmith_tracing_enabled() is True


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


def test_wrap_node_keeps_result_thin() -> None:
    async def handler(_state):
        return {"ok": True}

    wrapped = wrap_node(
        handler,
        workflow="digest.planner",
        lane="planner",
        name="test_node",
    )
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


def test_wrap_traceable_run_wraps_chain_node() -> None:
    async def handler(_state):
        return {"ok": True}

    wrapped = wrap_traceable_run(
        handler,
        name="generic_node",
        run_type="chain",
        workflow="digest.planner",
        lane="planner",
    )

    result = asyncio.run(wrapped({"subject": "demo"}))

    assert result == {"ok": True}


def test_wrap_workflow_node_accepts_legacy_parameter_names() -> None:
    async def handler(_state):
        return {"ok": True}

    wrapped = wrap_workflow_node(
        handler,
        workflow_name="digest.planner",
        lane="planner",
        node_name="legacy_node",
    )

    result = asyncio.run(wrapped({"subject": "demo"}))

    assert result == {"ok": True}


def test_node_short_alias_wraps_node() -> None:
    @node(
        workflow="digest.planner",
        lane="planner",
        name="short_alias_node",
    )
    async def handler(_state):
        return {"ok": True}

    result = asyncio.run(handler({"subject": "demo"}))

    assert result == {"ok": True}


def test_traceable_run_unifies_chain_node_decorator() -> None:
    @traceable_run(
        name="unified_alias_node",
        run_type="chain",
        workflow="digest.planner",
        lane="planner",
    )
    async def handler(_state):
        return {"ok": True}

    result = asyncio.run(handler({"subject": "demo"}))

    assert result == {"ok": True}


def test_traceable_run_supports_prompt_function() -> None:
    @traceable_run(
        name="prompt_builder",
        run_type="prompt",
    )
    def build_prompt(subject: str) -> str:
        return f"teach {subject}"

    assert build_prompt("math") == "teach math"


def test_workflow_node_alias_wraps_node() -> None:
    @workflow_node(
        workflow="digest.docgen",
        lane="docgen",
        name="explicit_alias_node",
    )
    async def handler(_state):
        return {"ok": True}

    result = asyncio.run(handler({"subject": "demo"}))

    assert result == {"ok": True}


def test_runtime_stats_helpers_record_steps_and_emit_progress() -> None:
    payloads: list[dict[str, str]] = []

    async def callback(payload):
        payloads.append(payload)

    state = {"progress_callback": callback}

    record_step_start(state, name="load_context", kind="node")
    elapsed_ms = record_step_end(state, name="load_context", kind="node")
    asyncio.run(
        emit_progress(
            state,
            phase="planner",
            step="load_context",
            status="completed",
            message="已读取资料。",
        )
    )

    assert elapsed_ms >= 0
    assert state["runtime_steps"] == [
        {
            "name": "load_context",
            "kind": "node",
            "status": "ok",
            "elapsed_ms": elapsed_ms,
        }
    ]
    assert payloads == [
        {
            "phase": "planner",
            "step": "load_context",
            "status": "completed",
            "message": "已读取资料。",
        }
    ]


def test_tracked_step_unifies_runtime_progress_and_trace(monkeypatch) -> None:
    payloads: list[dict[str, str]] = []
    captured: dict[str, object] = {}

    async def callback(payload):
        payloads.append(payload)

    class DummyRun:
        def end(self, *, outputs):
            captured["outputs"] = outputs

    class DummyTraceContext:
        def __enter__(self):
            return DummyRun()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_trace_substep(name: str, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return DummyTraceContext()

    monkeypatch.setattr(runtime_stats_module, "trace_substep", fake_trace_substep)

    state = {"progress_callback": callback}

    async def run_step() -> None:
        async with tracked_step(
            state,
            name="prepare_shared_inputs",
            kind="substep",
            phase="planner",
            running_message="开始读取资料",
            completed_message="资料读取完成",
            trace_run_type="prompt",
            trace_metadata={"file_count": 2},
            trace_inputs={"user_goal_present": True},
        ) as step:
            step.set_outputs(source_packet_count=3)

    asyncio.run(run_step())

    assert state["runtime_steps"][0]["name"] == "prepare_shared_inputs"
    assert state["runtime_steps"][0]["kind"] == "substep"
    assert state["runtime_steps"][0]["status"] == "ok"
    assert captured["name"] == "prepare_shared_inputs"
    assert captured["kwargs"] == {
        "metadata": {"file_count": 2},
        "tags": None,
        "run_type": "prompt",
        "inputs": {"user_goal_present": True},
    }
    assert captured["outputs"]["source_packet_count"] == 3
    assert captured["outputs"]["status"] == "ok"
    assert captured["outputs"]["elapsed_ms"] >= 0
    assert payloads == [
        {
            "phase": "planner",
            "step": "prepare_shared_inputs",
            "status": "running",
            "message": "开始读取资料",
        },
        {
            "phase": "planner",
            "step": "prepare_shared_inputs",
            "status": "completed",
            "message": "资料读取完成",
        },
    ]


def test_normalize_langsmith_run_type_falls_back_to_tool() -> None:
    assert normalize_langsmith_run_type("prompt") == "prompt"
    assert normalize_langsmith_run_type("retriever") == "retriever"
    assert normalize_langsmith_run_type("not-a-run-type") == "tool"
