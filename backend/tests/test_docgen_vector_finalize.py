from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes import sync_knowledge_graph


def _capability(*, queryable: bool, writable: bool = True, mode: str = "enabled") -> SimpleNamespace:
    return SimpleNamespace(
        binding=SimpleNamespace(mode=SimpleNamespace(value=mode)),
        queryable=queryable,
        writable=writable,
        status=SimpleNamespace(notice="向量索引不可查询"),
    )


def test_vector_finalize_skips_ready_or_disabled_courses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync_knowledge_graph, "_vector_capability", lambda _course_id: _capability(queryable=True))
    assert asyncio.run(
        sync_knowledge_graph._ensure_course_vector_index(course_id="course-ready", file_ids=["f1"])
    ) == ("ready", 0)

    monkeypatch.setattr(
        sync_knowledge_graph,
        "_vector_capability",
        lambda _course_id: _capability(queryable=False, writable=False, mode="disabled"),
    )
    assert asyncio.run(
        sync_knowledge_graph._ensure_course_vector_index(course_id="course-disabled", file_ids=["f1"])
    ) == ("skipped_disabled", 0)


def test_vector_finalize_rebuilds_missing_index_and_verifies_queryability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capabilities = iter(
        [
            _capability(queryable=False),
            _capability(queryable=True),
        ]
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(sync_knowledge_graph, "_vector_capability", lambda _course_id: next(capabilities))

    async def fake_index(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(chunk_ids=[1, 2])

    monkeypatch.setattr(sync_knowledge_graph, "index_course_files_for_retrieval", fake_index)
    monkeypatch.setattr(
        sync_knowledge_graph,
        "_indexed_vector_chunk_ids",
        lambda **_kwargs: {1, 2},
    )

    result = asyncio.run(
        sync_knowledge_graph._ensure_course_vector_index(
            course_id="course-missing",
            file_ids=["f1", "f1", "f2"],
        )
    )

    assert result == ("rebuilt", 2)
    assert calls == [
        {
            "course_id": "course-missing",
            "file_ids": ["f1", "f2"],
            "reason": "digest.docgen.finalize_vector_index.files.attempt_1",
            "raise_errors": True,
        }
    ]


def test_vector_finalize_indexes_published_docs_without_uploaded_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capabilities = iter(
        [
            _capability(queryable=False),
            _capability(queryable=True),
        ]
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(sync_knowledge_graph, "_vector_capability", lambda _course_id: next(capabilities))

    async def fake_index_published(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(chunk_ids=[11, 12])

    monkeypatch.setattr(
        sync_knowledge_graph,
        "index_published_knowledge_docs_for_retrieval",
        fake_index_published,
    )
    monkeypatch.setattr(
        sync_knowledge_graph,
        "_indexed_vector_chunk_ids",
        lambda **_kwargs: {11, 12},
    )

    result = asyncio.run(
        sync_knowledge_graph._ensure_course_vector_index(
            course_id="course-published",
            file_ids=[],
            published_markdown="# 第一章\n\n训练数据代表性决定模型输出边界。",
        )
    )

    assert result == ("rebuilt", 2)
    assert calls == [
        {
            "course_id": "course-published",
            "markdown": "# 第一章\n\n训练数据代表性决定模型输出边界。",
            "reason": "digest.docgen.finalize_vector_index.published_docs.attempt_1",
            "raise_errors": True,
        }
    ]


def test_vector_finalize_fails_clearly_when_rebuild_never_becomes_queryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sync_knowledge_graph,
        "_vector_capability",
        lambda _course_id: _capability(queryable=False),
    )

    async def fake_index(**_kwargs):
        return SimpleNamespace(chunk_ids=[1])

    monkeypatch.setattr(sync_knowledge_graph, "index_course_files_for_retrieval", fake_index)
    monkeypatch.setattr(
        sync_knowledge_graph,
        "_indexed_vector_chunk_ids",
        lambda **_kwargs: set(),
    )

    with pytest.raises(RuntimeError, match="still not queryable"):
        asyncio.run(
            sync_knowledge_graph._ensure_course_vector_index(
                course_id="course-broken",
                file_ids=["f1"],
            )
        )


@pytest.mark.anyio
async def test_graph_sync_and_vector_finalize_start_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    async def wait_for_peer(name: str):
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()

    async def fake_graph_sync(**_kwargs):
        await wait_for_peer("graph")
        return "completed"

    async def fake_vector_finalize(**_kwargs):
        await wait_for_peer("vector")
        return "ready", 0

    monkeypatch.setattr(
        sync_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )
    monkeypatch.setattr(sync_knowledge_graph, "capture_llm_runtime_snapshot", lambda: SimpleNamespace())
    monkeypatch.setattr(sync_knowledge_graph, "run_graph_docs_sync_auto_build", fake_graph_sync)
    monkeypatch.setattr(sync_knowledge_graph, "_ensure_course_vector_index", fake_vector_finalize)
    monkeypatch.setattr(sync_knowledge_graph, "read_knowledge_build_runtime", lambda *_args, **_kwargs: None)

    node = sync_knowledge_graph.build_sync_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course-parallel-finalize")
    )
    result = await asyncio.wait_for(
        node(
            {
                "course_id": "course-parallel-finalize",
                "requested_at": datetime(2026, 8, 9, tzinfo=timezone.utc),
                "build_group_id": "group-parallel-finalize",
                "build_session_id": "session-parallel-finalize",
                "file_ids": ["f1"],
            }
        ),
        timeout=1,
    )

    assert started == {"graph", "vector"}
    assert result["graph_sync_status"] == "completed"
    assert result["kg_prefetch_status"] == "completed"
    assert result["kg_prefetch_ready"] is True
    assert result["kg_prefetch_metrics"]["prefetch_status"] == "completed"
    assert result["vector_index_status"] == "ready"


@pytest.mark.anyio
async def test_vector_failure_waits_for_graph_sync_to_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    graph_can_finish = asyncio.Event()
    graph_finished = asyncio.Event()
    vector_failed = asyncio.Event()

    async def fake_graph_sync(**_kwargs):
        await graph_can_finish.wait()
        graph_finished.set()
        return "completed"

    async def fake_vector_finalize(**_kwargs):
        vector_failed.set()
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(
        sync_knowledge_graph,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )
    monkeypatch.setattr(sync_knowledge_graph, "capture_llm_runtime_snapshot", lambda: SimpleNamespace())
    monkeypatch.setattr(sync_knowledge_graph, "run_graph_docs_sync_auto_build", fake_graph_sync)
    monkeypatch.setattr(sync_knowledge_graph, "_ensure_course_vector_index", fake_vector_finalize)

    node = sync_knowledge_graph.build_sync_knowledge_graph_node(
        context=WorkflowContext(workflow_name="digest.docgen", course_id="course-failed-vector")
    )
    node_task = asyncio.create_task(
        node(
            {
                "course_id": "course-failed-vector",
                "requested_at": datetime(2026, 8, 9, tzinfo=timezone.utc),
                "build_group_id": "group-failed-vector",
                "build_session_id": "session-failed-vector",
                "file_ids": ["f1"],
            }
        )
    )

    await asyncio.wait_for(vector_failed.wait(), timeout=1)
    await asyncio.sleep(0)
    assert not node_task.done()

    graph_can_finish.set()
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await asyncio.wait_for(node_task, timeout=1)
    assert graph_finished.is_set()
