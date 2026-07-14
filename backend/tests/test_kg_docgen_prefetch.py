from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.shared.infra.observability import trace as trace_module
from app.workflows.digest.kg_doc_sync.lib import prefetch
from app.workflows.digest.kg_doc_sync.lib.models import SectionExtractionRecord


def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("configured", "global_limit", "expected"),
    [
        (12, 12, 2),
        (6, 10, 2),
        (1, 10, 1),
        (6, 2, 1),
        (6, 1, 1),
    ],
)
def test_prefetch_concurrency_limit_reserves_foreground_capacity(
    configured: int,
    global_limit: int,
    expected: int,
) -> None:
    assert (
        prefetch._prefetch_concurrency_limit(configured, global_limit=global_limit)
        == expected
    )


@pytest.mark.anyio
async def test_consume_docgen_kg_prefetch_cancels_unfinished_sidecar() -> None:
    key = ("course_prefetch_test", "build_prefetch_test")
    started = asyncio.Event()
    release = asyncio.Event()
    was_cancelled = False

    async def _runner() -> None:
        nonlocal was_cancelled
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    task = asyncio.create_task(_runner())
    await started.wait()
    cache = prefetch._PrefetchCache(course_id=key[0], build_session_id=key[1], task=task)
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    try:
        records, metrics = await prefetch.consume_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0.01,
        )

        assert records == []
        assert metrics["prefetch_status"] == "consumed_cancelled"
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

        with prefetch._LOCK:
            assert prefetch._CACHES.get(key) is None
        assert was_cancelled
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_await_docgen_kg_prefetch_keeps_completed_cache_for_final_sync() -> None:
    key = ("course_prefetch_ready", "build_prefetch_ready")
    record = SectionExtractionRecord(
        section_key="chapter:1",
        content_hash="hash-1",
        task_index=1,
        source_chapter_index=1,
        source_kind="chapter",
        title="矩阵乘法",
    )
    cache = prefetch._PrefetchCache(
        course_id=key[0],
        build_session_id=key[1],
        records=[record],
        status="completed",
    )
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    try:
        metrics = await prefetch.await_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0.01,
        )

        assert metrics["prefetch_status"] == "completed"
        assert metrics["prefetch_section_count"] == 1
        assert metrics["prefetch_ready"] == 1
        snapshot_records, snapshot_metrics = prefetch.snapshot_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
        )
        assert snapshot_records == [record]
        assert snapshot_metrics["prefetch_status"] == "completed"
        with prefetch._LOCK:
            assert prefetch._CACHES.get(key) is cache

        records, consumed_metrics = await prefetch.consume_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0,
        )
        assert records == [record]
        assert consumed_metrics["prefetch_status"] == "completed"
        with prefetch._LOCK:
            assert prefetch._CACHES.get(key) is None
    finally:
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_start_docgen_kg_prefetch_preserves_existing_records_during_refresh(monkeypatch) -> None:
    key = ("course_prefetch_refresh", "build_prefetch_refresh")
    prior_record = SectionExtractionRecord(
        section_key="chapter:brief:1",
        content_hash="brief-hash-1",
        task_index=1,
        source_chapter_index=1,
        source_kind="chapter_brief",
        title="矩阵乘法 brief",
    )
    cache = prefetch._PrefetchCache(
        course_id=key[0],
        build_session_id=key[1],
        records=[prior_record],
        status="completed",
    )
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    monkeypatch.setattr(
        prefetch,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(
                sync_after_docgen=True,
                prefetch_during_docgen=True,
                prefetch_concurrency=1,
            )
        ),
    )

    refreshed_task: asyncio.Task[None] | None = None
    started = prefetch.start_docgen_kg_prefetch(
        course_id=key[0],
        build_session_id=key[1],
        chapters=[{"chapter_index": 1, "title": "矩阵乘法", "markdown": "# 矩阵乘法\n\n## 行列配对\n\n正文"}],
        document_backbone={},
        docgen_manifest={"kg_prefetch_phase": "enhanced_chapters"},
    )

    try:
        assert started is True
        with prefetch._LOCK:
            refreshed = prefetch._CACHES[key]
            assert refreshed is not cache
            assert refreshed.records == [prior_record]
            assert refreshed.metrics["prefetch_prior_section_count"] == 1
            assert refreshed.metrics["prefetch_prior_status"] == "completed"
            refreshed_task = refreshed.task
    finally:
        prefetch.cancel_docgen_kg_prefetch(course_id=key[0], build_session_id=key[1])
        if refreshed_task is not None:
            await asyncio.gather(refreshed_task, return_exceptions=True)
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_incremental_prefetch_does_not_cancel_running_refresh(monkeypatch) -> None:
    key = ("course_prefetch_incremental", "build_prefetch_incremental")
    release = asyncio.Event()
    was_cancelled = False

    async def _running_refresh() -> None:
        nonlocal was_cancelled
        try:
            await release.wait()
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    running_task = asyncio.create_task(_running_refresh())
    cache = prefetch._PrefetchCache(course_id=key[0], build_session_id=key[1], task=running_task)
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    monkeypatch.setattr(
        prefetch,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(
                sync_after_docgen=True,
                prefetch_during_docgen=True,
                prefetch_concurrency=1,
            )
        ),
    )

    incremental_started = prefetch.start_docgen_kg_prefetch_incremental(
        course_id=key[0],
        build_session_id=key[1],
        chapters=[{"chapter_index": 2, "title": "应用题训练", "markdown": "# 应用题训练\n\n正文"}],
        document_backbone={},
        docgen_manifest={"kg_prefetch_phase": "reviewed_chapter_incremental"},
    )

    try:
        assert incremental_started is True
        assert running_task.cancelled() is False
        assert was_cancelled is False
        with prefetch._LOCK:
            active = prefetch._CACHES[key]
            assert active is cache
            assert active.task is running_task
            assert len(active.tasks) == 1
            assert active.metrics["prefetch_incremental_task_count"] == 1
    finally:
        prefetch.cancel_docgen_kg_prefetch(course_id=key[0], build_session_id=key[1])
        release.set()
        await asyncio.gather(running_task, *cache.tasks, return_exceptions=True)
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_await_docgen_kg_prefetch_tracks_incremental_tasks() -> None:
    key = ("course_prefetch_incremental_wait", "build_prefetch_incremental_wait")
    release = asyncio.Event()

    async def _incremental_task() -> None:
        await release.wait()

    task = asyncio.create_task(_incremental_task())
    cache = prefetch._PrefetchCache(
        course_id=key[0],
        build_session_id=key[1],
        tasks=[task],
        status="running",
    )
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    try:
        pending_metrics = await prefetch.await_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0.01,
        )
        assert pending_metrics["prefetch_ready"] == 0
        assert pending_metrics["prefetch_active_task_count"] == 1

        release.set()
        await task
        ready_metrics = await prefetch.await_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0,
        )
        assert ready_metrics["prefetch_status"] == "completed"
        assert ready_metrics["prefetch_ready"] == 1
        assert ready_metrics["prefetch_active_task_count"] == 0
    finally:
        prefetch.cancel_docgen_kg_prefetch(course_id=key[0], build_session_id=key[1])
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_completed_prefetch_refresh_prioritizes_fresh_records(monkeypatch) -> None:
    key = ("course_prefetch_fresh", "build_prefetch_fresh")
    prior_record = SectionExtractionRecord(
        section_key="chapter:1",
        content_hash="brief-hash",
        task_index=1,
        source_chapter_index=1,
        source_kind="chapter_brief",
        title="brief",
    )
    fresh_record = SectionExtractionRecord(
        section_key="chapter:1",
        content_hash="final-hash",
        task_index=1,
        source_chapter_index=1,
        source_kind="chapter_final",
        title="final",
    )
    with prefetch._LOCK:
        prefetch._CACHES[key] = prefetch._PrefetchCache(
            course_id=key[0],
            build_session_id=key[1],
            records=[prior_record],
            status="completed",
        )

    @contextmanager
    def fake_managed_session() -> Iterator[None]:
        yield None

    async def fake_extract_knowledge_graph_section_records_async(**kwargs):
        on_record = kwargs.get("on_record")
        if callable(on_record):
            on_record(fresh_record)
        return [fresh_record], {"prefetch_section_count": 1, "prefetch_failed_section_count": 0}

    monkeypatch.setattr(prefetch, "_PREFETCH_START_DELAY_S", 0)
    monkeypatch.setattr(prefetch, "managed_session", fake_managed_session)
    monkeypatch.setattr(prefetch, "load_course_llm_context", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        prefetch,
        "extract_knowledge_graph_section_records_async",
        fake_extract_knowledge_graph_section_records_async,
    )
    monkeypatch.setattr(
        prefetch,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(
                sync_after_docgen=True,
                prefetch_during_docgen=True,
                prefetch_concurrency=1,
            )
        ),
    )

    started = prefetch.start_docgen_kg_prefetch(
        course_id=key[0],
        build_session_id=key[1],
        chapters=[{"chapter_index": 1, "title": "final", "markdown": "# final\n\n## fresh\n\n正文"}],
        document_backbone={},
        docgen_manifest={"kg_prefetch_phase": "final_locked_markdown"},
    )

    try:
        assert started is True
        metrics = await prefetch.await_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=1,
        )
        records, _snapshot_metrics = prefetch.snapshot_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
        )

        assert metrics["prefetch_status"] == "completed"
        assert [record.content_hash for record in records] == ["final-hash", "brief-hash"]
        assert metrics["prefetch_prior_section_count"] == 1
    finally:
        prefetch.cancel_docgen_kg_prefetch(course_id=key[0], build_session_id=key[1])
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_start_docgen_kg_prefetch_caps_background_concurrency(monkeypatch) -> None:
    key = ("course_prefetch_concurrency", "build_prefetch_concurrency")
    captured_concurrency: list[int] = []
    captured_traces: list[dict[str, object]] = []

    class FakeTraceRun:
        def __init__(self) -> None:
            self.outputs: dict[str, object] | None = None

        def end(self, outputs=None) -> None:
            self.outputs = dict(outputs or {})

    @contextmanager
    def fake_managed_session() -> Iterator[None]:
        yield None

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        run = FakeTraceRun()
        captured_traces.append({"kwargs": kwargs, "run": run})
        yield run

    @contextmanager
    def fake_tracing_context(**_kwargs):
        yield None

    async def fake_extract_knowledge_graph_section_records_async(**kwargs):
        captured_concurrency.append(int(kwargs["concurrency_limit"]))
        return [], {"prefetch_section_count": 0, "prefetch_failed_section_count": 0}

    monkeypatch.setattr(prefetch, "_PREFETCH_START_DELAY_S", 0)
    monkeypatch.setattr(prefetch, "_graph_llm_concurrency_cap", lambda: 10)
    monkeypatch.setattr(prefetch, "managed_session", fake_managed_session)
    monkeypatch.setattr(prefetch, "load_course_llm_context", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        prefetch,
        "extract_knowledge_graph_section_records_async",
        fake_extract_knowledge_graph_section_records_async,
    )
    monkeypatch.setattr(prefetch, "langsmith_trace", fake_langsmith_trace)
    monkeypatch.setattr(prefetch, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(
        prefetch,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_graph=SimpleNamespace(
                sync_after_docgen=True,
                prefetch_during_docgen=True,
                prefetch_concurrency=6,
            )
        ),
    )

    started = prefetch.start_docgen_kg_prefetch(
        course_id=key[0],
        build_session_id=key[1],
        chapters=[{"chapter_index": 1, "title": "final", "markdown": "# final\n\n正文"}],
        document_backbone={},
        docgen_manifest={"kg_prefetch_phase": "final_locked_markdown"},
    )

    try:
        assert started is True
        metrics = await prefetch.await_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=1,
        )

        assert captured_concurrency == [2]
        assert len(captured_traces) == 1
        trace_kwargs = captured_traces[0]["kwargs"]
        assert trace_kwargs["name"] == "KG：DocGen 预取"
        assert trace_kwargs["inputs"]["concurrency_limit"] == 2
        assert trace_kwargs["extra_metadata"]["background_sidecar"] == "kg_docgen_prefetch"
        assert metrics["prefetch_configured_concurrency"] == 6
        assert metrics["prefetch_llm_concurrency_cap"] == 10
        assert metrics["prefetch_effective_concurrency"] == 2
        run = captured_traces[0]["run"]
        assert isinstance(run, FakeTraceRun)
        assert run.outputs is not None
        assert run.outputs["concurrency_limit"] == 2
    finally:
        prefetch.cancel_docgen_kg_prefetch(course_id=key[0], build_session_id=key[1])
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)


@pytest.mark.anyio
async def test_prefetch_trace_handles_expected_cancellation_without_swallowing(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []
    captured_runs: list[object] = []
    handled_cancellations: list[bool] = []
    cancellation = asyncio.CancelledError("superseded speculative prefetch")

    class FakeTraceRun:
        def __init__(self) -> None:
            self.outputs: dict[str, object] = {}
            self.error: str | None = None
            self.end_calls: list[dict[str, object | None]] = []

        def end(self, *, outputs=None, error=None) -> None:
            self.end_calls.append({"outputs": outputs, "error": error})
            self.outputs.update(dict(outputs or {}))
            if error is not None:
                self.error = str(error)

    @contextmanager
    def fake_tracing_context(**_kwargs):
        yield None

    @contextmanager
    def fake_langsmith_trace_run(**kwargs):
        run = FakeTraceRun()
        captured_calls.append(dict(kwargs))
        captured_runs.append(run)
        try:
            yield run
        except BaseException as exc:
            handled = isinstance(exc, kwargs.get("exceptions_to_handle") or ())
            handled_cancellations.append(handled)
            run.end(error=None if handled else repr(exc))
            raise

    @contextmanager
    def fake_runtime_snapshot(snapshot):
        yield snapshot

    async def fake_extract_knowledge_graph_section_records_async(**_kwargs):
        with trace_module.langsmith_trace(name="nested prefetch llm", run_type="llm"):
            raise cancellation

    monkeypatch.setattr(trace_module, "langsmith_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace_module, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(trace_module, "langsmith_trace_run", fake_langsmith_trace_run)
    monkeypatch.setattr(prefetch, "tracing_context", fake_tracing_context)
    monkeypatch.setattr(prefetch, "use_llm_runtime_snapshot", fake_runtime_snapshot)
    monkeypatch.setattr(
        prefetch,
        "extract_knowledge_graph_section_records_async",
        fake_extract_knowledge_graph_section_records_async,
    )

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await prefetch._extract_prefetch_records_with_trace(
            course_id="course_prefetch_cancel",
            build_session_id="build_prefetch_cancel",
            markdown="# chapter",
            chapters=[{"chapter_index": 1, "title": "chapter"}],
            course_context="",
            structured_context={},
            docgen_manifest={"kg_prefetch_phase": "enhanced_chapters"},
            snapshot=object(),
            concurrency=1,
            configured_concurrency=1,
            llm_concurrency_cap=4,
            incremental=False,
            on_record=lambda _record: None,
        )

    assert exc_info.value is cancellation
    assert [call["name"] for call in captured_calls] == [
        "KG：DocGen 预取",
        "nested prefetch llm",
    ]
    assert all(
        call.get("exceptions_to_handle") == (asyncio.CancelledError,)
        for call in captured_calls
    )
    assert handled_cancellations == [True, True]
    expected_outputs = {
        "trace_outcome": "cancelled_expected",
        "cancellation_scope": "kg_docgen_prefetch_sidecar",
    }
    assert all(
        isinstance(run, FakeTraceRun) and run.outputs == expected_outputs
        for run in captured_runs
    )
    assert all(
        isinstance(run, FakeTraceRun)
        and run.error is None
        and len(run.end_calls) == 2
        for run in captured_runs
    )
