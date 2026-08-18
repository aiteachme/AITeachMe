from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.shared.infra.observability import trace as trace_module
from app.shared.infra.llm_support import image as llm_image
from app.shared.infra.llm_support import observability as llm_observability
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import ToolRegistry, _tool_trace_inputs
from app.shared.infra.workflow import authoring as workflow_authoring
from app.shared.infra.workflow import runtime as workflow_runtime
from app.workflows.common import prompt_tracing
from app.workflows.digest.kg_doc_sync.lib import prefetch as kg_prefetch


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


def test_prompt_builder_trace_does_not_require_secondary_feature_flag(monkeypatch) -> None:
    trace_call: dict[str, Any] = {}
    trace_outputs: dict[str, Any] = {}

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        trace_call.update(kwargs)
        yield SimpleNamespace(end=lambda **end_kwargs: trace_outputs.update(end_kwargs))

    monkeypatch.delenv("AITM_TRACE_PROMPT_BUILDERS", raising=False)
    monkeypatch.setattr(prompt_tracing, "langsmith_trace", fake_langsmith_trace)
    monkeypatch.setattr(
        prompt_tracing,
        "get_llm_trace_context",
        lambda: SimpleNamespace(
            course_id="course-trace",
            build_session_id="build-trace",
            workflow="digest.docgen",
            lane="docgen",
            node="generate_chapter",
        ),
    )
    monkeypatch.setattr(
        prompt_tracing,
        "sanitize_langsmith_input",
        lambda value, *, field_name: value,
    )
    monkeypatch.setattr(
        prompt_tracing,
        "sanitize_langsmith_output",
        lambda value, *, field_name: value,
    )
    messages = [{"role": "user", "content": "生成课程章节"}]

    result = prompt_tracing.trace_prompt_build(
        "chapter_generation",
        inputs={"chapter": 1},
        output=messages,
    )

    assert result is messages
    assert trace_call["name"] == "Prompt：chapter_generation"
    assert trace_call["course_id"] == "course-trace"
    assert trace_outputs == {"outputs": {"prompt": messages}}


def test_prompt_builder_trace_compacts_large_inputs_and_outputs(monkeypatch) -> None:
    trace_call: dict[str, Any] = {}
    trace_outputs: dict[str, Any] = {}

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        trace_call.update(kwargs)
        yield SimpleNamespace(end=lambda **end_kwargs: trace_outputs.update(end_kwargs))

    monkeypatch.setattr(prompt_tracing, "langsmith_trace", fake_langsmith_trace)
    monkeypatch.setattr(prompt_tracing, "get_llm_trace_context", lambda: SimpleNamespace(
        course_id="course-trace",
        build_session_id="build-trace",
        workflow="digest.docgen",
        lane="docgen",
        node="generate_chapter",
    ))
    monkeypatch.setattr(prompt_tracing, "sanitize_langsmith_input", lambda value, *, field_name: value)
    monkeypatch.setattr(prompt_tracing, "sanitize_langsmith_output", lambda value, *, field_name: value)
    messages = [{"role": "user", "content": "章节材料" * 12000}]

    result = prompt_tracing.trace_prompt_build(
        "chapter_generation",
        inputs={"context": "检索上下文" * 12000},
        output=messages,
    )

    assert result is messages
    compact_input = trace_call["inputs"]
    compact_output = trace_outputs["outputs"]["prompt"]
    for compact in (compact_input, compact_output):
        assert compact["truncated"] is True
        assert compact["original_json_bytes"] > prompt_tracing._PROMPT_TRACE_JSON_BUDGET_BYTES
        assert len(compact["sha256"]) == 64
        assert len(json.dumps(compact, ensure_ascii=False).encode("utf-8")) <= prompt_tracing._PROMPT_TRACE_JSON_BUDGET_BYTES


@pytest.mark.anyio
async def test_langsmith_flush_is_bounded_and_best_effort(monkeypatch) -> None:
    calls: list[float] = []
    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(
        trace_module.langsmith_run_trees,
        "_CLIENT",
        SimpleNamespace(flush=lambda *, timeout: calls.append(timeout)),
    )

    assert await trace_module.flush_langsmith_traces(timeout_s=2.5) is True
    assert calls == [2.5]

    monkeypatch.setattr(
        trace_module.langsmith_run_trees,
        "_CLIENT",
        SimpleNamespace(flush=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))),
    )
    assert await trace_module.flush_langsmith_traces(timeout_s=1.0) is False


@pytest.mark.anyio
async def test_langsmith_flush_does_not_initialize_client_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(
        trace_module.langsmith_run_trees,
        "_CLIENT",
        None,
    )

    assert await trace_module.flush_langsmith_traces(timeout_s=1.0) is False


def test_langsmith_parent_headers_are_detached(monkeypatch) -> None:
    headers = {"langsmith-trace": "trace-id", "baggage": "project_name=test"}
    monkeypatch.setattr(trace_module, "langsmith_tracing_requested", lambda: True)
    monkeypatch.setattr(
        trace_module,
        "get_current_run_tree",
        lambda: SimpleNamespace(to_headers=lambda: headers),
    )

    captured = trace_module.capture_langsmith_parent_headers()
    headers["langsmith-trace"] = "changed"

    assert captured == {"langsmith-trace": "trace-id", "baggage": "project_name=test"}


@pytest.mark.anyio
async def test_kg_prefetch_restores_captured_parent_headers(monkeypatch) -> None:
    tracing_calls: list[dict[str, Any]] = []

    @contextmanager
    def fake_context(**kwargs):
        tracing_calls.append(dict(kwargs))
        yield

    @contextmanager
    def passthrough(*_args, **_kwargs):
        yield

    @contextmanager
    def fake_trace(**_kwargs):
        yield None

    async def fake_extract(**_kwargs):
        return [], {"completed_section_count": 0}

    monkeypatch.setattr(kg_prefetch, "tracing_context", fake_context)
    monkeypatch.setattr(kg_prefetch, "langsmith_expected_cancellation_scope", passthrough)
    monkeypatch.setattr(kg_prefetch, "use_llm_runtime_snapshot", passthrough)
    monkeypatch.setattr(kg_prefetch, "llm_trace_scope", passthrough)
    monkeypatch.setattr(kg_prefetch, "langsmith_trace", fake_trace)
    monkeypatch.setattr(kg_prefetch, "extract_knowledge_graph_section_records_async", fake_extract)
    parent_headers = {"langsmith-trace": "trace-id"}

    records, metrics = await kg_prefetch._extract_prefetch_records_with_trace(
        course_id="course-trace",
        build_session_id="build-trace",
        markdown="# 章节",
        chapters=[{"chapter_index": 1, "markdown": "# 章节"}],
        course_context=None,
        structured_context={},
        docgen_manifest={"kg_prefetch_phase": "enhanced_document"},
        snapshot=SimpleNamespace(),
        concurrency=1,
        configured_concurrency=1,
        llm_concurrency_cap=1,
        incremental=False,
        on_record=lambda _record: None,
        parent_headers=parent_headers,
    )

    assert records == []
    assert metrics == {"completed_section_count": 0}
    assert tracing_calls == [{"parent": parent_headers}]


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


def test_traceable_with_context_respects_child_run_suppression(monkeypatch) -> None:
    traced_calls: list[str] = []
    metadata_calls: list[str] = []

    def fake_traceable(**_kwargs):
        def decorator(func):
            def wrapper(*args, langsmith_extra=None, **kwargs):
                del langsmith_extra
                traced_calls.append("traced")
                return func(*args, **kwargs)

            return wrapper

        return decorator

    monkeypatch.setattr(trace_module, "traceable", fake_traceable)
    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)

    @trace_module.traceable_with_context(
        name="test.suppressed_trace",
        metadata_factory=lambda *_args, **_kwargs: metadata_calls.append("metadata") or {},
    )
    def traced(value: str) -> str:
        return value

    with trace_module.suppress_langsmith_child_runs():
        assert traced("value") == "value"

    assert traced_calls == []
    assert metadata_calls == []


def test_image_trace_inputs_respect_capture_setting(monkeypatch) -> None:
    monkeypatch.setattr(llm_image, "langsmith_capture_inputs_enabled", lambda: False)

    inputs = llm_image._langsmith_image_inputs(
        model="image-model",
        prompt="private image prompt",
        size="1024x1024",
        image_count=1,
    )

    assert inputs == {
        "model": "image-model",
        "prompt": "[redacted]",
        "size": "1024x1024",
        "n": 1,
    }


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


def test_langsmith_trace_write_failure_does_not_change_business_result(monkeypatch) -> None:
    @contextmanager
    def fake_tracing_context(**_kwargs):
        yield

    @contextmanager
    def failing_trace_run(**_kwargs):
        yield SimpleNamespace(end=lambda **_kwargs: None)
        raise RuntimeError("zstd compress error: Allocation error : not enough memory")

    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace_module, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(trace_module, "langsmith_trace_run", failing_trace_run)

    with trace_module.langsmith_trace(name="memory pressure", run_type="llm"):
        result = "generated content"

    assert result == "generated content"


def test_langsmith_trace_write_failure_preserves_business_error(monkeypatch) -> None:
    @contextmanager
    def fake_tracing_context(**_kwargs):
        yield

    @contextmanager
    def failing_trace_run(**_kwargs):
        try:
            yield SimpleNamespace(end=lambda **_kwargs: None)
        finally:
            raise RuntimeError("zstd trace failure")

    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace_module, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(trace_module, "langsmith_trace_run", failing_trace_run)

    with pytest.raises(ValueError, match="business failure"):
        with trace_module.langsmith_trace(name="preserve error", run_type="llm"):
            raise ValueError("business failure")


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
