from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow import runtime as workflow_runtime
from app.workflows.digest.kg_doc_sync.lib import builds as kg_builds


class TinyState(TypedDict, total=False):
    value: int
    error: str | None


class _FakeTraceRun:
    def end(self, outputs=None):
        self.outputs = outputs


def _build_tiny_graph() -> StateGraph:
    graph = StateGraph(TinyState)

    async def inc(state: TinyState) -> dict[str, int]:
        return {"value": int(state.get("value") or 0) + 1}

    graph.add_node("inc", inc)
    graph.set_entry_point("inc")
    graph.add_edge("inc", END)
    return graph


@pytest.mark.anyio
async def test_run_state_graph_can_skip_root_trace(monkeypatch) -> None:
    root_trace_names: list[str] = []

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        root_trace_names.append(str(kwargs.get("name") or ""))
        yield _FakeTraceRun()

    monkeypatch.setattr(workflow_runtime, "langsmith_trace", fake_langsmith_trace)

    result = await workflow_runtime.run_state_graph(
        workflow_name="test.embedded",
        graph_builder=_build_tiny_graph,
        initial_state={"value": 1},
        context=WorkflowContext(
            workflow_name="test.embedded",
            course_id="course_test",
            metadata={"langsmith_run_name": "embedded graph"},
        ),
        trace_as_root=False,
    )

    assert not result.failed
    assert result.require_value()["value"] == 2
    assert root_trace_names == []


@pytest.mark.anyio
async def test_run_state_graph_keeps_root_trace_by_default(monkeypatch) -> None:
    root_trace_names: list[str] = []

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        root_trace_names.append(str(kwargs.get("name") or ""))
        yield _FakeTraceRun()

    monkeypatch.setattr(workflow_runtime, "langsmith_trace", fake_langsmith_trace)

    result = await workflow_runtime.run_state_graph(
        workflow_name="test.root",
        graph_builder=_build_tiny_graph,
        initial_state={"value": 1},
        context=WorkflowContext(
            workflow_name="test.root",
            course_id="course_test",
            metadata={"langsmith_run_name": "root graph"},
        ),
    )

    assert not result.failed
    assert result.require_value()["value"] == 2
    assert root_trace_names == ["root graph"]


@pytest.mark.anyio
async def test_auto_graph_sync_embeds_in_docgen_trace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_graph_docs_sync_build(**kwargs):
        captured.update(kwargs)
        return "completed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 2)

    status = await kg_builds.run_graph_docs_sync_auto_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
        docgen_state={},
    )

    assert status == "completed"
    assert captured["embedded_in_parent_trace"] is True


@pytest.mark.anyio
async def test_auto_graph_sync_prewarms_exam_only_for_first_revision(monkeypatch) -> None:
    spawned: list[dict[str, object]] = []

    class FakeBackgroundRegistry:
        def spawn(self, coro, **kwargs):
            coro.close()
            spawned.append(kwargs)
            return object()

    async def fake_run_graph_docs_sync_build(**kwargs):
        assert kwargs["early_units_callback"] is None
        return "completed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 1)

    status = await kg_builds.run_graph_docs_sync_auto_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
        docgen_state={},
        background_task_registry=FakeBackgroundRegistry(),
    )

    assert status == "completed"
    assert len(spawned) == 1
    assert spawned[0]["kind"] == "exam.prewarm"
    assert str(spawned[0]["dedupe_key"]).endswith(":default:1")


@pytest.mark.anyio
async def test_auto_graph_sync_skips_exam_prewarm_after_initial_revision(monkeypatch) -> None:
    spawned: list[dict[str, object]] = []

    class FakeBackgroundRegistry:
        def spawn(self, coro, **kwargs):
            coro.close()
            spawned.append(kwargs)
            return object()

    async def fake_run_graph_docs_sync_build(**kwargs):
        assert kwargs["early_units_callback"] is None
        return "completed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 2)

    status = await kg_builds.run_graph_docs_sync_auto_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
        docgen_state={},
        background_task_registry=FakeBackgroundRegistry(),
    )

    assert status == "completed"
    assert spawned == []


@pytest.mark.anyio
async def test_auto_graph_sync_skips_exam_prewarm_when_not_completed(monkeypatch) -> None:
    spawned: list[dict[str, object]] = []

    class FakeBackgroundRegistry:
        def spawn(self, coro, **kwargs):
            coro.close()
            spawned.append(kwargs)
            return object()

    async def fake_run_graph_docs_sync_build(**kwargs):
        assert kwargs["early_units_callback"] is None
        return "partial_failed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 1)

    status = await kg_builds.run_graph_docs_sync_auto_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
        docgen_state={},
        background_task_registry=FakeBackgroundRegistry(),
    )

    assert status == "partial_failed"
    assert spawned == []


@pytest.mark.anyio
async def test_manual_graph_sync_keeps_own_root_trace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_graph_docs_sync_build(**kwargs):
        captured.update(kwargs)
        return "completed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)

    await kg_builds.run_graph_docs_sync_manual_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
    )

    assert captured.get("embedded_in_parent_trace") is False
