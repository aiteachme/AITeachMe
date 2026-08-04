from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any

import pytest

from app.shared.infra.observability import trace as trace_module
from app.shared.infra.llm_support import observability as llm_observability
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry, _tool_trace_inputs
from app.shared.infra.workflow import authoring as workflow_authoring
from app.shared.infra.workflow import runtime as workflow_runtime


def test_graph_tracing_context_respects_runtime_disabled(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    @contextmanager
    def fake_tracing_context(**kwargs):
        calls.append(dict(kwargs))
        yield

    monkeypatch.setattr(workflow_runtime, "langsmith_child_runs_suppressed", lambda: False)
    monkeypatch.setattr(workflow_runtime, "langsmith_tracing_enabled", lambda: False)
    monkeypatch.setattr(workflow_runtime, "tracing_context", fake_tracing_context)

    with workflow_runtime._graph_tracing_context():
        pass

    assert calls == [{"enabled": False}]


def test_graph_tracing_context_preserves_parent_and_suppresses_state_dump(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    @contextmanager
    def fake_tracing_context(**kwargs):
        calls.append(dict(kwargs))
        yield

    monkeypatch.setattr(workflow_runtime, "langsmith_child_runs_suppressed", lambda: False)
    monkeypatch.setattr(workflow_runtime, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(workflow_runtime, "get_current_run_tree", lambda: "parent-run")
    monkeypatch.setattr(workflow_runtime, "tracing_context", fake_tracing_context)

    with workflow_runtime._graph_tracing_context():
        pass

    assert calls == [{"enabled": False, "parent": "parent-run"}]


def test_compact_graph_outputs_keep_counts_without_markdown(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_runtime,
        "sanitize_langsmith_output",
        lambda value, *, field_name: value,
    )

    outputs = workflow_runtime._compact_graph_outputs(
        {
            "course_id": "course_1",
            "course_name": "初数14天通关",
            "merged_markdown": "# " + "x" * 100,
            "enriched_markdown": "# " + "y" * 80,
            "chapter_drafts": [{"markdown": "large"}],
            "enhanced_chapter_drafts": [{"markdown": "large"}],
            "reviewed_chapter_drafts": [{"markdown": "large"}],
            "llm_calls_total": 36,
            "llm_calls_skipped": 0,
        },
        elapsed_ms=123,
    )

    assert outputs["phase"] == "output"
    assert outputs["course_id"] == "course_1"
    assert outputs["merged_markdown_chars"] == 102
    assert outputs["chapter_drafts_count"] == 1
    assert outputs["enhanced_chapter_drafts_count"] == 1
    assert outputs["reviewed_chapter_drafts_count"] == 1
    assert outputs["llm_calls_total"] == 36
    assert "merged_markdown" not in outputs
    assert "chapter_drafts" not in outputs


def test_node_trace_outputs_summarize_large_values(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_authoring,
        "sanitize_langsmith_output",
        lambda value, *, field_name: value,
    )

    outputs = workflow_authoring._node_trace_outputs(
        {
            "merged_markdown": "x" * 1000,
            "chapter_drafts": [{"markdown": "large"}],
            "llm_calls_total": 2,
        },
        output_keys=("merged_markdown", "chapter_drafts"),
        elapsed_ms=12,
    )

    assert outputs["elapsed_ms"] == 12
    assert outputs["merged_markdown_summary"] == {"type": "str", "chars": 1000}
    assert outputs["chapter_drafts_summary"] == {"type": "list", "count": 1}
    assert outputs["llm_calls_total"] == 2
    assert "merged_markdown" not in outputs
    assert "chapter_drafts" not in outputs


def test_traceable_with_context_defaults_to_traceable_io(monkeypatch) -> None:
    recorded: dict[str, Any] = {}

    def fake_traceable(**kwargs):
        recorded.update(kwargs)

        def decorator(func):
            def wrapper(*args, langsmith_extra=None, **kwargs):
                del langsmith_extra
                return func(*args, **kwargs)

            return wrapper

        return decorator

    monkeypatch.setattr(trace_module, "traceable", fake_traceable)
    @trace_module.traceable_with_context(name="test.safe_trace", run_type="chain")
    def traced(secret: str) -> str:
        return secret

    assert traced("value") == "value"

    process_inputs = recorded["process_inputs"]
    process_outputs = recorded["process_outputs"]
    assert recorded["enabled"] is True
    assert process_inputs({"secret": "student answer", "model": "safe-model"}) == {
        "secret": "student answer",
        "model": "safe-model",
    }
    assert process_outputs({"content": "private explanation"}) == {"content": "private explanation"}


def test_expected_trace_exceptions_are_forwarded_and_not_swallowed(monkeypatch) -> None:
    trace_calls: list[dict[str, Any]] = []
    trace_runs: list[Any] = []

    class FakeTraceRun:
        def __init__(self) -> None:
            self.outputs: dict[str, Any] = {}
            self.error: str | None = None
            self.end_calls: list[dict[str, Any]] = []

        def end(self, *, outputs=None, error=None) -> None:
            self.end_calls.append({"outputs": outputs, "error": error})
            self.outputs.update(dict(outputs or {}))
            if error is not None:
                self.error = str(error)

    @contextmanager
    def fake_tracing_context(**_kwargs):
        yield

    @contextmanager
    def fake_langsmith_trace_run(**kwargs):
        run = FakeTraceRun()
        trace_calls.append(dict(kwargs))
        trace_runs.append(run)
        try:
            yield run
        except BaseException as exc:
            handled = isinstance(exc, kwargs.get("exceptions_to_handle") or ())
            run.end(error=None if handled else repr(exc))
            raise

    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace_module, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(trace_module, "langsmith_trace_run", fake_langsmith_trace_run)

    with trace_module.langsmith_trace(name="before", run_type="chain"):
        pass

    cancellation = asyncio.CancelledError("expected sidecar stop")
    with pytest.raises(asyncio.CancelledError) as exc_info:
        with trace_module.langsmith_expected_cancellation_scope(
            "kg_docgen_prefetch_sidecar"
        ):
            with trace_module.langsmith_trace(name="sidecar", run_type="chain"):
                raise cancellation

    ordinary_cancellation = asyncio.CancelledError("user cancellation")
    with pytest.raises(asyncio.CancelledError) as ordinary_exc_info:
        with trace_module.langsmith_trace(name="after", run_type="chain"):
            raise ordinary_cancellation

    with pytest.raises(GeneratorExit):
        with trace_module.langsmith_trace(
            name="stream closed",
            run_type="llm",
            expected_exceptions=(GeneratorExit,),
        ):
            raise GeneratorExit()

    assert exc_info.value is cancellation
    assert ordinary_exc_info.value is ordinary_cancellation
    assert [call.get("exceptions_to_handle") for call in trace_calls] == [
        None,
        (asyncio.CancelledError,),
        None,
        (GeneratorExit,),
    ]
    assert trace_runs[1].outputs == {
        "trace_outcome": "cancelled_expected",
        "cancellation_scope": "kg_docgen_prefetch_sidecar",
    }
    assert trace_runs[1].error is None
    assert trace_runs[1].end_calls == [
        {
            "outputs": {
                "trace_outcome": "cancelled_expected",
                "cancellation_scope": "kg_docgen_prefetch_sidecar",
            },
            "error": None,
        },
        {"outputs": None, "error": None},
    ]
    assert trace_runs[2].outputs == {}
    assert trace_runs[2].error == repr(ordinary_cancellation)
    assert trace_runs[3].error is None


def test_langsmith_capture_text_follows_cloud_defaults_and_explicit_overrides(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "is_local_mode", lambda: False)
    cases = [
        ({}, False, False, "[redacted]", "[redacted]"),
        (
            {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"},
            True,
            True,
            "student answer",
            "private explanation",
        ),
        (
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_CAPTURE_INPUTS": "false",
                "LANGSMITH_CAPTURE_OUTPUTS": "false",
            },
            False,
            False,
            "[redacted]",
            "[redacted]",
        ),
        (
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_CAPTURE_OUTPUTS": "false",
            },
            True,
            False,
            "student answer",
            "[redacted]",
        ),
    ]

    for env, capture_inputs, capture_outputs, expected_input, expected_output in cases:
        for name in (
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_CAPTURE_INPUTS",
            "LANGSMITH_CAPTURE_OUTPUTS",
        ):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        assert trace_module.langsmith_capture_inputs_enabled() is capture_inputs
        assert trace_module.langsmith_capture_outputs_enabled() is capture_outputs
        assert trace_module.sanitize_langsmith_input({"content": "student answer"}) == {
            "content": expected_input
        }
        assert trace_module.sanitize_langsmith_output({"content": "private explanation"}) == {
            "content": expected_output
        }


def test_llm_trace_kwargs_record_api_mode_and_provider_native_tools(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability, "langsmith_capture_inputs_enabled", lambda: False)

    kwargs = llm_observability._langsmith_trace_kwargs(
        task_type="chat",
        call_model="gpt-5.5",
        provider="openai",
        model_name="gpt-5.5",
        mode="stream_responses",
        messages=[{"role": "user", "content": "hello"}],
        call_kwargs={
            "model": "gpt-5.5",
            "reasoning": {"effort": "high"},
            "tools": [
                {"type": "web_search"},
                {"type": "file_search", "vector_store_ids": ["vs_test"]},
            ],
        },
    )

    metadata = kwargs["extra_metadata"]
    assert metadata["llm_initial_api_mode"] == "responses"
    assert metadata["ls_invocation_params"]["reasoning"] == {"effort": "high"}
    assert metadata["ls_reasoning_effort"] == "high"
    assert metadata["llm_tool_types"] == ["web_search", "file_search"]
    assert metadata["llm_provider_native_tool_types"] == ["web_search", "file_search"]


def test_llm_outputs_record_final_api_mode(monkeypatch) -> None:
    monkeypatch.setattr(llm_observability, "langsmith_capture_outputs_enabled", lambda: True)

    outputs = llm_observability._langsmith_outputs(
        text="ok",
        extra_outputs={
            "llm_initial_api_mode": "responses",
            "llm_final_api_mode": "chat_completions",
            "llm_api_mode_changed": True,
            "llm_auto_responses_chat_fallback": True,
            "llm_final_api_mode_route_reason": "auto_responses_unsupported_chat_fallback",
        },
    )

    assert outputs["llm_initial_api_mode"] == "responses"
    assert outputs["llm_final_api_mode"] == "chat_completions"
    assert outputs["llm_api_mode_changed"] is True
    assert outputs["llm_auto_responses_chat_fallback"] is True
    assert outputs["llm_final_api_mode_route_reason"] == "auto_responses_unsupported_chat_fallback"


def test_tool_trace_inputs_redact_hidden_arguments(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "langsmith_capture_inputs_enabled", lambda: True)

    definition = ToolDefinition(
        name="search_kb",
        description="search",
        parameters={"type": "object", "properties": {}},
        handler=lambda: None,
        hidden_args=["course_id"],
    )

    payload = _tool_trace_inputs({
        "tool_name": "search_kb",
        "arguments": {
            "query": "kinematics",
            "course_id": "course_secret",
        },
        "tool_definition": definition,
    })

    assert payload["visible_argument_names"] == ["query"]
    assert payload["hidden_argument_names"] == ["course_id"]
    assert payload["arguments"] == {"query": "kinematics"}


def test_tool_registry_execute_forwards_langsmith_metadata(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="trace_test",
            description="trace",
            parameters={"type": "object", "properties": {}},
            handler=lambda query, course_id=None: f"{query}:{course_id}",
            hidden_args=["course_id"],
        )
    )
    captured: dict[str, Any] = {}

    async def fake_run_traced_tool(**kwargs):
        captured.update(kwargs)
        return {"result": "ok", "trace": {"success": True}}

    monkeypatch.setattr(registry, "_run_traced_tool", fake_run_traced_tool)

    result = asyncio.run(
        registry.execute(
            "trace_test",
            query="hello",
            course_id="course_1",
            _trace_metadata={
                "tool_call_id": "call_1",
                "tool_call_index": 2,
            },
        )
    )

    assert result == "ok"
    assert captured["arguments"] == {"query": "hello", "course_id": "course_1"}
    assert captured["langsmith_extra"]["metadata"]["tool_call_id"] == "call_1"
    assert captured["langsmith_extra"]["metadata"]["tool_call_index"] == 2
