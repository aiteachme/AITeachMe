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
