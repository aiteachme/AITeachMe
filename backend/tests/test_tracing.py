from __future__ import annotations

import asyncio

import pytest

from app.shared.infra import llm as llm_module
from app.shared.infra.config import Settings, get_settings
from app.shared.infra.llm_support import observability as llm_observability_module
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.traced_execution import BaseTracedExecution, TracedExecutionContext, TracedExecutionResult
from app.shared.infra.tracing import LLMCallRecord, LLMCallTracker, get_llm_trace_context
from app.shared.infra import tracing as tracing_module
from app.workflows.digest.docgen.runtime import DocGenWriterRuntime
from app.workflows.common.context import LANGGRAPH_DEV_SUBJECT, WorkflowContext


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


