from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.shared.infra.observability import trace as trace_module
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
    assert process_inputs({"secret": "student answer", "model": "safe-model"}) == {
        "secret": "student answer",
        "model": "safe-model",
    }
    assert process_outputs({"content": "private explanation"}) == {"content": "private explanation"}


def test_langsmith_capture_text_defaults_to_redacted_outside_local(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "is_local_mode", lambda: False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_CAPTURE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_CAPTURE_OUTPUTS", raising=False)

    assert not trace_module.langsmith_capture_inputs_enabled()
    assert not trace_module.langsmith_capture_outputs_enabled()
    assert trace_module.sanitize_langsmith_input({"content": "student answer"}) == {
        "content": "[redacted]"
    }
    assert trace_module.sanitize_langsmith_output({"content": "private explanation"}) == {
        "content": "[redacted]"
    }


def test_langsmith_capture_text_defaults_to_enabled_when_langsmith_configured(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "is_local_mode", lambda: False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.delenv("LANGSMITH_CAPTURE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_CAPTURE_OUTPUTS", raising=False)

    assert trace_module.langsmith_capture_inputs_enabled()
    assert trace_module.langsmith_capture_outputs_enabled()
    assert trace_module.sanitize_langsmith_input({"content": "student answer"}) == {
        "content": "student answer"
    }
    assert trace_module.sanitize_langsmith_output({"content": "private explanation"}) == {
        "content": "private explanation"
    }


def test_langsmith_capture_text_can_be_disabled_when_langsmith_configured(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "is_local_mode", lambda: False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_CAPTURE_INPUTS", "false")
    monkeypatch.setenv("LANGSMITH_CAPTURE_OUTPUTS", "false")

    assert not trace_module.langsmith_capture_inputs_enabled()
    assert not trace_module.langsmith_capture_outputs_enabled()


def test_langsmith_capture_specific_env_overrides_default_capture(monkeypatch) -> None:
    monkeypatch.setattr(trace_module, "is_local_mode", lambda: False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_CAPTURE_OUTPUTS", "false")
    monkeypatch.delenv("LANGSMITH_CAPTURE_INPUTS", raising=False)

    assert trace_module.langsmith_capture_inputs_enabled()
    assert not trace_module.langsmith_capture_outputs_enabled()
