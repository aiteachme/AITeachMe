import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from app.models import Course
from app.shared.infra.exceptions import CourseBuildLockConflictError
from app.shared.infra.storage import build_course_storage_scope
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow import runtime as workflow_runtime
from app.workflows.digest.kg_doc_sync.lib import builds as kg_builds

MANUAL_GRAPH_COURSE_ID = "course_test00000000"


class TinyState(TypedDict, total=False):
    value: int
    error: str | None


class _FakeTraceRun:
    def end(self, outputs=None):
        self.outputs = outputs


def _patch_manual_graph_trigger_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kg_builds, "read_knowledge_build_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        kg_builds,
        "load_knowledge_doc_sync_input",
        lambda *args, **kwargs: SimpleNamespace(
            markdown="# Knowledge",
            source="published",
            structured_context={"doc_version_no": 1, "chapters": []},
        ),
    )


def _build_tiny_graph() -> StateGraph:
    graph = StateGraph(TinyState)

    async def inc(state: TinyState) -> dict[str, int]:
        return {"value": int(state.get("value") or 0) + 1}

    graph.add_node("inc", inc)
    graph.set_entry_point("inc")
    graph.add_edge("inc", END)
    return graph


def test_manual_graph_trigger_requires_course_build_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manual_graph_trigger_inputs(monkeypatch)
    monkeypatch.setattr(kg_builds, "acquire_knowledge_build_lock", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        kg_builds,
        "_write_graph_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status must follow lock acquisition")),
    )

    with pytest.raises(CourseBuildLockConflictError):
        kg_builds.trigger_graph_docs_sync_manual_build(
            object(),  # type: ignore[arg-type]
            course=Course(id=MANUAL_GRAPH_COURSE_ID, user_id="user_test", name="Test"),
        )


def test_manual_graph_trigger_releases_lock_when_spawn_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manual_graph_trigger_inputs(monkeypatch)
    released: list[tuple[str, str]] = []
    spawned: list[dict[str, object]] = []

    class _FailingRegistry:
        @staticmethod
        def spawn(_coro, **kwargs):
            spawned.append(kwargs)
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr(kg_builds, "acquire_knowledge_build_lock", lambda *args, **kwargs: True)
    monkeypatch.setattr(kg_builds, "_write_graph_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(kg_builds, "capture_llm_runtime_snapshot", lambda: None)
    monkeypatch.setattr(
        kg_builds,
        "release_knowledge_build_lock",
        lambda course_id, *, build_group_id, **_kwargs: released.append((course_id, build_group_id)) or True,
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        kg_builds.trigger_graph_docs_sync_manual_build(
            object(),  # type: ignore[arg-type]
            course=Course(id=MANUAL_GRAPH_COURSE_ID, user_id="user_test", name="Test"),
            background_task_registry=_FailingRegistry(),
        )

    assert len(released) == 1
    assert released[0][0] == MANUAL_GRAPH_COURSE_ID
    assert spawned[0]["name"] == f"knowledge.build.graph:{MANUAL_GRAPH_COURSE_ID}:{released[0][1]}"


@pytest.mark.anyio
async def test_manual_graph_owner_lifecycle_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    released: list[tuple[str, str]] = []
    scope = build_course_storage_scope(user_id="user_test", course_id=MANUAL_GRAPH_COURSE_ID)

    async def fake_heartbeat(**_kwargs) -> None:
        await asyncio.Future()

    async def fake_run_graph_docs_sync_build(**_kwargs) -> str:
        return "failed"

    monkeypatch.setattr(kg_builds, "maintain_knowledge_build_lock_lease", fake_heartbeat)
    monkeypatch.setattr(kg_builds, "_still_owns_knowledge_build_lock", lambda **_kwargs: True)
    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(
        kg_builds,
        "release_knowledge_build_lock",
        lambda course_id, *, build_group_id, **_kwargs: released.append((course_id, build_group_id)) or True,
    )

    await kg_builds.run_graph_docs_sync_manual_build(
        course_id=MANUAL_GRAPH_COURSE_ID,
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_test",
        build_session_id="session_test",
        file_ids=[],
        prompt=None,
        course_scope=scope,
        manage_build_lock=True,
    )

    assert released == [(MANUAL_GRAPH_COURSE_ID, "group_test")]


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
async def test_manual_graph_sync_keeps_own_root_trace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_graph_docs_sync_build(**kwargs):
        captured.update(kwargs)
        return "completed"

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 2)

    await kg_builds.run_graph_docs_sync_manual_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
    )

    assert captured.get("embedded_in_parent_trace") is False


@pytest.mark.anyio
async def test_manual_graph_sync_prewarms_exam_after_completed_first_revision(monkeypatch) -> None:
    prewarm_calls: list[dict[str, object]] = []

    async def fake_run_graph_docs_sync_build(**kwargs):
        return "completed"

    async def fake_trigger_default_exam_prewarm_when_units_ready(**kwargs):
        prewarm_calls.append(kwargs)

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        kg_builds,
        "_trigger_default_exam_prewarm_when_units_ready",
        fake_trigger_default_exam_prewarm_when_units_ready,
    )

    await kg_builds.run_graph_docs_sync_manual_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
    )
    await asyncio.sleep(0)

    assert prewarm_calls == [
        {
            "course_id": "course_test",
            "min_build_revision_no": 1,
            "wait_for_units_timeout_s": 30.0,
            "llm_snapshot": None,
        }
    ]


@pytest.mark.anyio
async def test_manual_graph_sync_registers_exam_prewarm_with_background_registry(monkeypatch) -> None:
    async def fake_run_graph_docs_sync_build(**kwargs):
        return "completed"

    class FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def spawn(self, coro, **kwargs):
            self.calls.append(kwargs)
            coro.close()

    registry = FakeRegistry()

    monkeypatch.setattr(kg_builds, "_run_graph_docs_sync_build", fake_run_graph_docs_sync_build)
    monkeypatch.setattr(kg_builds, "_current_doc_version_no", lambda *args, **kwargs: 1)

    await kg_builds.run_graph_docs_sync_manual_build(
        course_id="course_test",
        requested_at=datetime.now(timezone.utc),
        build_group_id="group_1",
        build_session_id="session_1",
        file_ids=[],
        prompt=None,
        background_task_registry=registry,
    )

    assert registry.calls == [
        {
            "kind": "exam.prewarm",
            "course_id": "course_test",
            "name": "exam.prewarm.completed_build:course_test:1",
            "dedupe_key": "exam.prewarm.completed_build:course_test:default:1",
        }
    ]
