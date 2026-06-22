from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.shared.infra.knowledge.build_store as build_store
from app.shared.infra.storage import build_course_storage_scope


class _JsonStore:
    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}
        self.deleted: list[str] = []
        self.deleted_prefixes: list[str] = []

    async def read_json(self, key: str, model):
        raw = self.payloads.get(key)
        return model.model_validate_json(raw) if raw is not None else None

    async def write_json(self, key: str, model) -> None:
        self.payloads[key] = model.model_dump_json()

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.payloads.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        keys = [key for key in self.payloads if key.startswith(prefix)]
        for key in keys:
            self.payloads.pop(key, None)
        return len(keys)

    async def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self.payloads if key.startswith(prefix))


def _scope():
    return build_course_storage_scope(user_id="user_a", course_id="course_runtime00001")


def test_runtime_status_hydration_sanitizes_progress_metrics_and_events() -> None:
    requested_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=requested_at,
        build_kind="graph",
        status="running",
        stage="generating_chapters",
        processed_chunks=2,
        doc_sync_section_count=3,
        doc_sync_llm_section_count=4,
        digest_mode="sprint",
        sample_nodes=[
            {"name": "Limit", "type": "Concept"},
            {"name": "", "type": "Ignored"},
            {"name": "Derivative", "type": "Procedure"},
            {"name": "Integral", "type": "Concept"},
        ],
        metrics={
            "doc_sync_elapsed_ms": "1200",
            "graph_component_count": "-1",
            "prefetch_failed_section_count": "bad",
        },
        chapter_progress=[
            {"chapter_index": "2", "title": "B", "status": "planned"},
            {"chapter_index": "1", "title": "A", "status": "generated", "source_count": "2"},
        ],
        chapter_previews=[
            {"chapter_index": 0, "title": "drop"},
            {"chapter_index": 2, "title": "B", "latest_headings": ["h1", "h1", "h2"], "updated_at": requested_at},
        ],
        merge_preview={"latest_chapter_titles": ["A", "A", "B"], "draft_excerpt": " draft ", "updated_at": requested_at},
        recent_events=[
            {"summary": "", "stage": "ignored"},
            {
                "stage": "generating_chapters",
                "summary": "chapter generated",
                "created_at": requested_at,
                "domains": ["math", "math", "cs"],
                "source_titles": ["Doc", "Doc"],
                "source_urls": ["https://example.test", "https://example.test"],
            },
        ],
    )

    hydrated = build_store._hydrate_runtime_status(status)

    assert hydrated.started_at == requested_at
    assert hydrated.progress_pct >= 56
    assert hydrated.estimated_remaining_seconds is not None
    assert hydrated.metrics["elapsed_ms"] == 1200
    assert hydrated.metrics["graph_component_count"] == 0
    assert hydrated.processed_chunks == 2
    assert [item["chapter_index"] for item in hydrated.chapter_progress] == [1, 2]
    assert hydrated.chapter_previews[0]["latest_headings"] == ["h1", "h2"]
    assert hydrated.merge_preview["latest_chapter_titles"] == ["A", "B"]
    assert hydrated.recent_events[0]["domains"] == ["math", "cs"]
    assert hydrated.sample_cards[0]["card_type"] == "mode"
    assert [card["title"] for card in hydrated.sample_cards[1:]] == ["Limit", "Derivative"]


def test_runtime_status_hydration_knows_docgen_graph_prepare_stage() -> None:
    status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=datetime.now(timezone.utc),
        build_kind="docgen",
        status="running",
        stage="preparing_knowledge_graph",
    )

    hydrated = build_store._hydrate_runtime_status(status)

    assert hydrated.progress_pct >= 85
    assert hydrated.current_stage_description == "正在准备可立即展示的知识图谱候选。"


def test_aggregate_status_prefers_blocking_lane_and_preserves_metrics() -> None:
    now = datetime.now(timezone.utc)
    docgen_done = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        status="completed",
        stage="completed",
        progress_pct=100,
    )
    graph_running = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="graph",
        status="running",
        stage="graph_docs_sync",
        progress_pct=30,
    )
    graph_failed = graph_running.model_copy(update={"status": "failed", "error_message": "boom"})

    assert build_store.build_aggregate_knowledge_build_status(None) is None
    assert build_store.build_aggregate_knowledge_build_status(build_store.KnowledgeBuildRuntimeEnvelope()) is None

    graph_only = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(graph_runtime=graph_running)
    )
    assert graph_only is not None
    assert graph_only.status == "running"
    assert graph_only.stage == "graph_docs_sync"

    docgen_failed = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(
            docgen_runtime=docgen_done.model_copy(update={"status": "failed", "stage": "failed", "error_message": "doc failed"}),
            graph_runtime=graph_running,
        )
    )
    assert docgen_failed is not None
    assert docgen_failed.status == "failed"
    assert docgen_failed.error_message == "doc failed"

    docgen_active_with_graph_expected = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(
            docgen_runtime=docgen_done.model_copy(update={"status": "running", "stage": "publishing", "progress_pct": 99}),
        ),
        graph_expected=True,
    )
    assert docgen_active_with_graph_expected is not None
    assert docgen_active_with_graph_expected.status == "running"
    assert docgen_active_with_graph_expected.progress_pct == 94

    graph_active = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(docgen_runtime=docgen_done, graph_runtime=graph_running)
    )
    assert graph_active is not None
    assert graph_active.status == "running"
    assert graph_active.stage == "graph_docs_sync"
    assert graph_active.progress_pct == 95
    assert graph_active.metrics == {"docgen_status": "completed", "graph_status": "running"}

    graph_requested_at = now + timedelta(minutes=3)
    separate_graph_active = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(
            docgen_runtime=docgen_done.model_copy(update={"build_group_id": "docgen-group-1"}),
            graph_runtime=graph_running.model_copy(
                update={
                    "requested_at": graph_requested_at,
                    "build_group_id": "graph-group-2",
                    "progress_pct": 94,
                }
            ),
        )
    )
    assert separate_graph_active is not None
    assert separate_graph_active.status == "running"
    assert separate_graph_active.requested_at == graph_requested_at
    assert separate_graph_active.build_group_id == "graph-group-2"
    assert separate_graph_active.progress_pct == 95

    graph_pending = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(docgen_runtime=docgen_done),
        graph_expected=True,
    )
    assert graph_pending is not None
    assert graph_pending.status == "running"
    assert graph_pending.stage == "graph_pending"
    assert graph_pending.progress_pct == 95

    partial = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(docgen_runtime=docgen_done, graph_runtime=graph_failed)
    )
    assert partial is not None
    assert partial.status == "partial_failed"
    assert partial.progress_pct == 100

    skipped = build_store.build_aggregate_knowledge_build_status(
        build_store.KnowledgeBuildRuntimeEnvelope(
            docgen_runtime=docgen_done,
            graph_runtime=graph_running.model_copy(update={"status": "skipped", "stage": "disabled"}),
        )
    )
    assert skipped is not None
    assert skipped.status == "completed"


def test_runtime_store_updates_docgen_graph_and_preview_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _JsonStore()
    scope = _scope()
    published_events: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(build_store, "get_content_store", lambda: store)
    monkeypatch.setattr(build_store, "publish_workflow_stream_event", lambda course_id, event, data: published_events.append((course_id, event, data)))

    docgen = build_store.update_knowledge_build_lane_status(
        "course_runtime00001",
        lane="docgen",
        course_scope=scope,
        requested_at=datetime.now(timezone.utc),
        build_group_id="group-1",
        status="running",
        stage="generating_chapters",
        progress_pct=10,
        digest_mode="systematic",
    )
    graph = build_store.update_knowledge_build_status(
        "course_runtime00001",
        course_scope=scope,
        build_kind="graph",
        status="running",
        stage="graph_docs_sync",
        metrics={"source_ref_count": "5"},
        doc_sync_elapsed_ms="100",
    )
    progress = build_store.upsert_knowledge_build_chapter_progress(
        "course_runtime00001",
        course_scope=scope,
        chapter_progress={"chapter_index": 1, "title": "A", "status": "generated", "source_count": 2},
    )
    preview = build_store.upsert_knowledge_build_chapter_preview(
        "course_runtime00001",
        course_scope=scope,
        chapter_preview={"chapter_index": 1, "title": "A", "excerpt": "hello", "latest_headings": ["h"]},
    )
    ignored_preview = build_store.upsert_knowledge_build_chapter_preview(
        "course_runtime00001",
        course_scope=scope,
        chapter_preview={"chapter_index": 0, "title": "ignored"},
    )
    event_status = build_store.append_knowledge_build_recent_event(
        "course_runtime00001",
        course_scope=scope,
        event={"stage": "generating_chapters", "summary": "generated chapter", "domains": ["math", "math"]},
        limit=3,
    )
    merge = build_store.update_knowledge_build_merge_preview(
        "course_runtime00001",
        course_scope=scope,
        merge_preview={"latest_chapter_titles": ["A", "A", "B"], "draft_excerpt": "draft"},
    )

    runtime = build_store.read_knowledge_build_runtime("course_runtime00001", course_scope=scope)
    legacy = build_store.read_knowledge_build_status("course_runtime00001", course_scope=scope)
    aggregate = build_store.read_knowledge_build_aggregate_status("course_runtime00001", course_scope=scope)

    assert docgen.build_group_id == "group-1"
    assert graph.metrics["source_ref_count"] == 5
    assert progress.chapter_progress[0]["source_count"] == 2
    assert preview.chapter_previews[0]["excerpt"] == "hello"
    assert ignored_preview.chapter_previews[0]["chapter_index"] == 1
    assert event_status.recent_events[0]["domains"] == ["math"]
    assert merge.merge_preview["latest_chapter_titles"] == ["A", "B"]
    assert runtime is not None
    assert runtime.docgen_runtime is not None
    assert runtime.graph_runtime is not None
    assert legacy is not None
    assert aggregate is not None
    assert aggregate.status == "running"
    assert scope.build_runtime_key() in store.payloads
    assert scope.build_status_key() in store.payloads
    assert ("course_runtime00001", "build_event", event_status.recent_events[0]) in published_events


@pytest.mark.parametrize(
    ("terminal_status", "expected_event"),
    [
        ("completed", "knowledge_build_completed"),
        ("failed", "knowledge_build_failed"),
        ("partial_failed", "knowledge_build_failed"),
        ("cancelled", "knowledge_build_cancelled"),
    ],
)
def test_docgen_terminal_analytics_fires_once_on_terminal_transition(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
    expected_event: str,
) -> None:
    store = _JsonStore()
    scope = _scope()
    captured: list[tuple[str, str, dict[str, object], object]] = []
    requested_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    started_at = requested_at + timedelta(seconds=1)
    finished_at = requested_at + timedelta(seconds=16)
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    monkeypatch.setattr(build_store, "get_content_store", lambda: store)
    monkeypatch.setattr(build_store, "is_local_mode", lambda: False)
    monkeypatch.setattr(build_store, "publish_workflow_stream_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_store,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(
            (event, distinct_id, properties or {}, timestamp)
        )
        or True,
    )

    terminal_runtime = build_store.update_knowledge_build_lane_status(
        "course_runtime00001",
        lane="docgen",
        course_scope=scope,
        requested_at=requested_at,
        build_group_id="group-1",
        status="running",
        stage="generating_chapters",
        started_at=started_at,
        source_file_ids=["file-1", "file-2"],
        digest_mode="systematic",
    )
    build_store.update_knowledge_build_lane_status(
        "course_runtime00001",
        lane="docgen",
        course_scope=scope,
        requested_at=requested_at,
        build_group_id="group-1",
        status=terminal_status,
        stage=terminal_status,
        finished_at=finished_at,
        published_doc_count=3,
    )
    build_store.update_knowledge_build_lane_status(
        "course_runtime00001",
        lane="docgen",
        course_scope=scope,
        requested_at=requested_at,
        build_group_id="group-1",
        status=terminal_status,
        stage=terminal_status,
    )
    build_store.update_knowledge_build_lane_status(
        "course_runtime00001",
        lane="graph",
        course_scope=scope,
        requested_at=requested_at,
        build_group_id="group-1",
        status="failed",
        stage="failed",
    )
    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=scope,
        user_id=None,
        status=terminal_runtime,
    )

    assert len(captured) == 1
    event, distinct_id, properties, timestamp = captured[0]
    assert event == expected_event
    assert distinct_id == "user_a"
    assert timestamp == finished_at
    insert_id = str(properties["$insert_id"])
    assert insert_id.startswith(f"{expected_event}:")
    assert len(insert_id.removeprefix(f"{expected_event}:")) == 32
    assert "course_runtime00001" not in insert_id
    assert "group-1" not in insert_id
    assert properties["analytics_source"] == "backend"
    assert properties["user_id_present"] is True
    assert properties["course_id_suffix"] == "ime00001"
    assert properties["build_kind"] == "docgen"
    assert properties["source_file_count"] == 2
    assert properties["published_doc_count"] == 3
    assert properties["duration_ms"] == 15000
    assert properties["status"] == terminal_status


def test_docgen_terminal_analytics_reserves_insert_id_during_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    requested_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=requested_at,
        started_at=requested_at + timedelta(seconds=1),
        finished_at=requested_at + timedelta(seconds=16),
        build_group_id="group-1",
        status="completed",
        stage="completed",
    )
    monkeypatch.setattr(build_store, "is_local_mode", lambda: False)

    def capture_once(event, *, distinct_id, properties=None, timestamp=None):
        captured.append(event)
        build_store._capture_docgen_terminal_analytics_event(
            course_id="course_runtime00001",
            course_scope=None,
            user_id="user_a",
            status=status,
        )
        return True

    monkeypatch.setattr(build_store, "capture_posthog_event", capture_once)

    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=None,
        user_id="user_a",
        status=status,
    )

    assert captured == ["knowledge_build_completed"]


def test_docgen_terminal_analytics_local_marker_blocks_duplicate_across_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: list[str] = []
    scope = _scope()
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    requested_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=requested_at,
        started_at=requested_at + timedelta(seconds=1),
        finished_at=requested_at + timedelta(seconds=16),
        build_group_id="group-1",
        status="completed",
        stage="completed",
    )
    monkeypatch.setattr(build_store, "get_runtime_data_dir", lambda: tmp_path)
    monkeypatch.setattr(build_store, "is_local_mode", lambda: True)
    monkeypatch.setattr(
        build_store,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(event) or True,
    )

    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=scope,
        user_id="user_a",
        status=status,
    )
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=scope,
        user_id="user_a",
        status=status,
    )

    assert captured == ["knowledge_build_completed"]
    assert len(list(tmp_path.rglob("*.posthog"))) == 1


def test_docgen_terminal_analytics_dedupes_enriched_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    requested_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    base_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=requested_at,
        finished_at=requested_at + timedelta(seconds=16),
        status="completed",
        stage="completed",
        published_doc_count=3,
    )
    enriched_status = base_status.model_copy(
        update={
            "build_group_id": "group-1",
            "build_session_id": "session-1",
            "planner_session_id": "planner-1",
            "confirmed_plan_id": "plan-1",
            "digest_mode": "sprint",
        }
    )
    monkeypatch.setattr(build_store, "is_local_mode", lambda: False)
    monkeypatch.setattr(
        build_store,
        "capture_posthog_event",
        lambda event, *, distinct_id, properties=None, timestamp=None: captured.append(
            {"event": event, "properties": properties or {}}
        )
        or True,
    )

    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=None,
        user_id="user_a",
        status=base_status,
    )
    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=None,
        user_id="user_a",
        status=enriched_status,
    )

    assert [item["event"] for item in captured] == ["knowledge_build_completed"]
    assert str(captured[0]["properties"]["$insert_id"]).startswith("knowledge_build_completed:")


def test_docgen_terminal_analytics_releases_insert_id_after_capture_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    build_store._POSTHOG_DOCGEN_TERMINAL_RESERVED_INSERT_IDS.clear()
    requested_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=requested_at,
        build_group_id="group-1",
        status="completed",
        stage="completed",
    )
    monkeypatch.setattr(build_store, "is_local_mode", lambda: False)

    def fail_then_succeed(event, *, distinct_id, properties=None, timestamp=None):
        attempts.append(event)
        return len(attempts) > 1

    monkeypatch.setattr(build_store, "capture_posthog_event", fail_then_succeed)

    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=None,
        user_id="user_a",
        status=status,
    )
    build_store._capture_docgen_terminal_analytics_event(
        course_id="course_runtime00001",
        course_scope=None,
        user_id="user_a",
        status=status,
    )

    assert attempts == ["knowledge_build_completed", "knowledge_build_completed"]


def test_local_build_lock_lifecycle_and_stale_recovery(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scope = _scope()
    monkeypatch.setattr(build_store, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(build_store, "get_runtime_data_dir", lambda: tmp_path)

    lock = build_store.KnowledgeBuildLock(
        requested_at=datetime.now(timezone.utc),
        build_group_id="group-1",
        source_file_ids=["file-1"],
        prompt="build",
    )

    assert build_store.read_knowledge_build_lock("course_runtime00001", course_scope=scope) is None
    assert build_store.acquire_knowledge_build_lock("course_runtime00001", lock, course_scope=scope) is True
    assert build_store.acquire_knowledge_build_lock("course_runtime00001", lock, course_scope=scope) is False
    assert build_store.is_knowledge_build_locked("course_runtime00001", course_scope=scope) is True
    assert build_store.read_knowledge_build_lock("course_runtime00001", course_scope=scope) == lock

    lock_path = build_store._local_build_lock_path(scope)
    lock_path.write_text("not-json", encoding="utf-8")
    assert build_store.read_knowledge_build_lock("course_runtime00001", course_scope=scope) is None

    stale = lock.model_copy(update={"requested_at": datetime.now(timezone.utc) - build_store.STALE_BUILD_LOCK_TTL - timedelta(seconds=1)})
    lock_path.write_text(stale.model_dump_json(), encoding="utf-8")
    assert build_store.acquire_knowledge_build_lock("course_runtime00001", lock, course_scope=scope) is True

    build_store.release_knowledge_build_lock("course_runtime00001", course_scope=scope)
    assert build_store.is_knowledge_build_locked("course_runtime00001", course_scope=scope) is False


def test_manifest_and_artifact_cleanup_respect_scope(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    store = _JsonStore()
    scope = _scope()
    monkeypatch.setattr(build_store, "get_content_store", lambda: store)
    monkeypatch.setattr(build_store, "get_runtime_data_dir", lambda: tmp_path)
    monkeypatch.setattr(build_store, "is_local_mode", lambda: True)
    monkeypatch.setattr(build_store, "is_cloud_mode", lambda: False)

    manifest = build_store.KnowledgeDocsManifest(
        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        version_no=2,
        chapter_count=2,
        chapter_titles=["A", "B"],
    )
    staged_manifest_key = build_store._staged_build_manifest_key(scope)
    store.payloads[staged_manifest_key] = manifest.model_dump_json()

    assert build_store.read_knowledge_manifest("course_runtime00001", course_scope=scope) == manifest
    assert scope.build_manifest_key() in store.payloads
    assert staged_manifest_key not in store.payloads

    for key in [
        scope.knowledge_doc_key("chapter_001.md"),
        scope.knowledge_doc_key("merged_knowledge_base.md"),
        scope.knowledge_doc_key("docgen_manifest.json"),
        scope.knowledge_doc_key("versions/1/chapter_001.md"),
        scope.knowledge_doc_key("notes.txt"),
        f"{scope.knowledge_build_prefix()}status.json",
        scope.build_runtime_key(),
    ]:
        store.payloads[key] = manifest.model_dump_json()

    build_dir = tmp_path / scope.namespace / "knowledge_markdowns" / "_build"
    build_dir.mkdir(parents=True)
    (build_dir / "temp.json").write_text("{}", encoding="utf-8")

    build_store.clear_current_published_knowledge_docs_files("course_runtime00001", course_scope=scope)
    assert scope.knowledge_doc_key("chapter_001.md") not in store.payloads
    assert scope.knowledge_doc_key("versions/1/chapter_001.md") in store.payloads

    build_store.clear_published_knowledge_docs_files("course_runtime00001", course_scope=scope)
    assert scope.knowledge_doc_key("versions/1/chapter_001.md") not in store.payloads
    assert scope.knowledge_doc_key("notes.txt") in store.payloads

    build_store.clear_knowledge_runtime_artifacts("course_runtime00001", course_scope=scope)
    assert scope.knowledge_build_prefix() in store.deleted_prefixes
    assert not build_dir.exists()
    assert scope.build_manifest_key() in store.deleted
    assert scope.build_runtime_key() in store.deleted
