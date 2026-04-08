from __future__ import annotations

import asyncio

import pytest

from app.shared.infra import llm as llm_module
from app.shared.infra.config import get_settings
from app.shared.infra.model_router import TaskType
from app.shared.infra.skills.base import BaseSkill, SkillContext, SkillResult
from app.shared.infra.tracing import LLMCallRecord, LLMCallTracker, get_llm_trace_context
from app.shared.infra import tracing as tracing_module
from app.workflows.common.context import LANGGRAPH_DEV_SUBJECT, WorkflowContext


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


def test_llm_call_tracker_trims_old_records(monkeypatch) -> None:
    monkeypatch.setenv("LLM_OBSERVABILITY_MAX_RECORDS", "2")
    tracker = LLMCallTracker()

    tracker.record(LLMCallRecord(task_type="chat", model="model-1", call_id="call-1"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-2", call_id="call-2"))
    tracker.record(LLMCallRecord(task_type="chat", model="model-3", call_id="call-3"))

    assert [record.call_id for record in tracker._records] == ["call-2", "call-3"]


def test_langsmith_tracing_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    assert tracing_module.langsmith_tracing_enabled() is False

    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    get_settings.cache_clear()

    assert tracing_module.langsmith_tracing_enabled() is True


def test_base_skill_run_sets_nested_llm_trace_scope() -> None:
    class DummySkill(BaseSkill):
        async def execute(self, **kwargs) -> SkillResult:
            del kwargs
            trace = get_llm_trace_context()
            return SkillResult(
                metadata={
                    "trace_workflow": trace.workflow,
                    "trace_lane": trace.lane,
                    "trace_node": trace.node,
                }
            )

    context = SkillContext(
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
    result = asyncio.run(DummySkill(context).run())

    assert result.metadata["trace_workflow"] == "digest.docgen.test"
    assert result.metadata["trace_lane"] == "docgen"
    assert result.metadata["trace_node"] == "skill.DummySkill"
