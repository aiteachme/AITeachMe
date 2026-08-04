from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
import app.shared.infra.knowledge.build_store as build_store
from app.models import Course, CourseFileLink, IngestStatus, RawFile, TaskStatus
from app.models.build_planner import ConfirmedBuildPlan
from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_graph_sync import KnowledgeGraphSyncRun
from app.schemas.knowledge import CourseVectorStatusResponse, KnowledgeBuildStatusResponse
from app.shared.infra.exceptions import (
    ConfirmedBuildPlanRequiredError,
    CourseBuildLockConflictError,
    NoReadyFilesForDocGenError,
)
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.common import build_lifecycle as common_build_lifecycle
from app.workflows.digest.common import cleanup as common_cleanup
from app.workflows.digest.docgen.lib import build_lifecycle
from app.workflows.digest.docgen.nodes import publish_document as publish_document_module
from app.workflows.digest.docgen.nodes import rollback_knowledge_graph as rollback_knowledge_graph_module


COURSE_ID = "course_docgen000000"
USER_ID = "user-docgen"


class _TextStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def read_text(self, key: str) -> str:
        return self.values.get(key, "")


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


def _seed_course_and_files(session: Session) -> Course:
    course = Course(
        id=COURSE_ID,
        user_id=USER_ID,
        name="Linear Algebra",
        description="Matrix course",
        user_intent="Build a study guide",
    )
    ready = RawFile(
        id="file-ready",
        user_id=USER_ID,
        filename="ready.md",
        filetype="md",
        file_path="ready.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        markdown_content="# Ready\nMatrix content.",
    )
    pending = RawFile(
        id="file-pending",
        user_id=USER_ID,
        filename="pending.pdf",
        filetype="pdf",
        file_path="pending.pdf",
        status=TaskStatus.PROCESSING.value,
        ingest_status=IngestStatus.PENDING.value,
        markdown_content="",
    )
    session.add(course)
    session.add_all([ready, pending])
    session.add_all(
        [
            CourseFileLink(user_id=USER_ID, course_id=COURSE_ID, file_id="file-ready"),
            CourseFileLink(user_id=USER_ID, course_id=COURSE_ID, file_id="file-pending"),
        ]
    )
    session.commit()
    session.refresh(course)
    return course


def _confirmed_plan(*, status: str = "confirmed") -> ConfirmedBuildPlan:
    return ConfirmedBuildPlan(
        id="plan-1",
        version_no=2,
        course_id=COURSE_ID,
        planner_session_id="planner-1",
        user_id=USER_ID,
        status=status,
        user_prompt="按矩阵和线性映射生成知识文档",
        digest_mode="systematic",
        selected_file_ids=["file-ready", "file-pending"],
        chapters=[
            {
                "chapter_index": 1,
                "title": "矩阵对象",
                "objective": "讲清矩阵基础",
                "required_elements": ["矩阵乘法"],
            },
            {
                "chapter_index": 2,
                "title": "线性映射",
                "objective": "讲清映射视角",
                "required_elements": ["基变换"],
            },
        ],
        build_constraints={"min_chapters": 2, "max_chapters": 2},
        plan="两章完成线性代数主线。",
        plan_json={
            "course_name": "线性代数",
            "course_icon": "calculator",
            "intent": "按矩阵和线性映射生成知识文档",
            "summary": "资料围绕矩阵对象和线性映射。",
            "suggestion": "如果更偏考试，可以增加题型训练。",
            "plan": "两章完成线性代数主线。",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "矩阵对象",
                    "objective": "讲清矩阵基础",
                    "required_elements": ["矩阵乘法"],
                },
                {
                    "chapter_index": 2,
                    "title": "线性映射",
                    "objective": "讲清映射视角",
                    "required_elements": ["基变换"],
                },
            ],
            "model_override": "primary",
        },
    )


def test_file_selection_and_trigger_docgen_build_write_runtime_contracts(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = _seed_course_and_files(session)
    statuses: list[dict[str, object]] = []
    locks: list[build_store.KnowledgeBuildLock] = []
    cleared_vectors: list[str] = []

    monkeypatch.setattr(
        build_lifecycle,
        "inspect_course_build_precheck",
        lambda *args, **kwargs: SimpleNamespace(requires_full_rebuild=True),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "resolve_course_build_vector_status",
        lambda *args, **kwargs: CourseVectorStatusResponse(mode="enabled", embedding_model="text-embedding"),
    )
    monkeypatch.setattr(build_lifecycle, "clear_chunk_vector_metadata", lambda _session, *, course_id: cleared_vectors.append(course_id))
    monkeypatch.setattr(build_lifecycle, "get_confirmed_build_plan", lambda *args, **kwargs: _confirmed_plan())
    monkeypatch.setattr(build_lifecycle, "_new_build_session_id", lambda: "build-group-1")
    monkeypatch.setattr(build_lifecycle, "_clear_docgen_staging_safely", lambda *args, **kwargs: None)

    def fake_acquire(_course_id: str, lock: build_store.KnowledgeBuildLock, **_kwargs) -> bool:
        locks.append(lock)
        return True

    def fake_status(course_id: str, *, lane: str, **kwargs):
        statuses.append({"course_id": course_id, "lane": lane, **kwargs})
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(build_lifecycle, "acquire_knowledge_build_lock", fake_acquire)
    monkeypatch.setattr(build_lifecycle, "update_knowledge_build_lane_status", fake_status)

    selected, ready_count = build_lifecycle._select_ready_docgen_files_by_ids(
        session,
        course_id=COURSE_ID,
        file_ids=["file-pending", "file-ready"],
    )
    build_data, accepted_file_ids, build_group_id = build_lifecycle.trigger_docgen_build(
        session,
        course=course,
        user_id=USER_ID,
        file_ids=["ignored-by-confirmed-plan"],
        prompt="用户临时输入会被 confirmed plan 覆盖",
        embedding_resolution=None,
        confirmed_plan_id="plan-1",
    )

    assert [item.id for item in selected] == ["file-ready"]
    assert ready_count == 1
    with pytest.raises(NoReadyFilesForDocGenError):
        build_lifecycle._select_ready_docgen_files_by_ids(
            session,
            course_id=COURSE_ID,
            file_ids=["file-pending"],
        )
    assert cleared_vectors == [COURSE_ID]
    assert accepted_file_ids == ["file-ready"]
    assert build_group_id == "build-group-1"
    assert build_data.accepted_file_ids == ["file-ready"]
    assert build_data.ready_file_count == 1
    assert build_data.prompt == "按矩阵和线性映射生成知识文档"
    assert build_data.digest_mode == "systematic"
    assert build_data.model_override == "primary"
    assert locks[0].source_file_ids == ["file-ready"]
    assert statuses[0]["status"] == "accepted"
    assert statuses[0]["planner_session_id"] == "planner-1"
    assert len(statuses[0]["chapter_progress"]) == 2


def test_trigger_docgen_build_rejects_missing_or_busy_confirmed_plan(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = _seed_course_and_files(session)
    monkeypatch.setattr(build_lifecycle, "inspect_course_build_precheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        build_lifecycle,
        "resolve_course_build_vector_status",
        lambda *args, **kwargs: CourseVectorStatusResponse(mode="disabled"),
    )

    with pytest.raises(ConfirmedBuildPlanRequiredError):
        build_lifecycle.trigger_docgen_build(
            session,
            course=course,
            user_id=USER_ID,
            file_ids=None,
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id=None,
        )

    monkeypatch.setattr(build_lifecycle, "get_confirmed_build_plan", lambda *args, **kwargs: _confirmed_plan(status="building"))
    with pytest.raises(CourseBuildLockConflictError):
        build_lifecycle.trigger_docgen_build(
            session,
            course=course,
            user_id=USER_ID,
            file_ids=None,
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id="plan-1",
        )


def test_trigger_docgen_build_does_not_mutate_vectors_before_lock(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = _seed_course_and_files(session)
    events: list[str] = []
    monkeypatch.setattr(build_lifecycle, "get_confirmed_build_plan", lambda *args, **kwargs: _confirmed_plan())
    monkeypatch.setattr(build_lifecycle, "_new_build_session_id", lambda: "build-group-conflict")
    monkeypatch.setattr(
        build_lifecycle,
        "acquire_knowledge_build_lock",
        lambda *args, **kwargs: events.append("acquire") or False,
    )
    monkeypatch.setattr(
        build_lifecycle,
        "inspect_course_build_precheck",
        lambda *args, **kwargs: events.append("inspect") or None,
    )
    monkeypatch.setattr(
        build_lifecycle,
        "resolve_course_build_vector_status",
        lambda *args, **kwargs: events.append("resolve") or CourseVectorStatusResponse(mode="disabled"),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "clear_chunk_vector_metadata",
        lambda *args, **kwargs: events.append("clear"),
    )

    with pytest.raises(CourseBuildLockConflictError):
        build_lifecycle.trigger_docgen_build(
            session,
            course=course,
            user_id=USER_ID,
            file_ids=None,
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id="plan-1",
        )

    assert events == ["acquire"]


def test_trigger_docgen_build_releases_lock_when_status_initialization_fails(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = _seed_course_and_files(session)
    released: list[tuple[str, str]] = []
    monkeypatch.setattr(
        build_lifecycle,
        "inspect_course_build_precheck",
        lambda *args, **kwargs: SimpleNamespace(requires_full_rebuild=False),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "resolve_course_build_vector_status",
        lambda *args, **kwargs: CourseVectorStatusResponse(mode="disabled"),
    )
    monkeypatch.setattr(build_lifecycle, "get_confirmed_build_plan", lambda *args, **kwargs: _confirmed_plan())
    monkeypatch.setattr(build_lifecycle, "_new_build_session_id", lambda: "build-group-release")
    monkeypatch.setattr(build_lifecycle, "_clear_docgen_staging_safely", lambda *args, **kwargs: None)
    monkeypatch.setattr(build_lifecycle, "acquire_knowledge_build_lock", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        build_lifecycle,
        "update_knowledge_build_lane_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("status write failed")),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "release_knowledge_build_lock",
        lambda course_id, *, build_group_id, **_kwargs: released.append((course_id, build_group_id)) or True,
    )

    with pytest.raises(RuntimeError, match="status write failed"):
        build_lifecycle.trigger_docgen_build(
            session,
            course=course,
            user_id=USER_ID,
            file_ids=["file-ready"],
            prompt=None,
            embedding_resolution=None,
            confirmed_plan_id="plan-1",
        )

    assert released == [(COURSE_ID, "build-group-release")]


class _NoopNodeLogger:
    def bind(self, **_kwargs):
        return self

    def info(self, *_args, **_kwargs) -> None:
        return None

    def error(self, *_args, **_kwargs) -> None:
        return None


def _publish_state() -> dict[str, object]:
    return {
        "course_id": COURSE_ID,
        "user_id": USER_ID,
        "build_group_id": "group-publish",
        "requested_at": datetime.now(timezone.utc),
        "chapter_metadatas": [
            {
                "chapter_index": 1,
                "title": "矩阵",
                "markdown": "# 矩阵\n\n正文",
            }
        ],
    }


def test_publish_document_rejects_lost_owner_before_shared_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: calls.append("status"),
    )

    async def fake_stage(**_kwargs):
        calls.append("stage")
        return SimpleNamespace(merged_markdown="", built_paths=[])

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(
        publish_document_module,
        "publish_staged_knowledge_docs",
        lambda **_kwargs: calls.append("publish") or [],
    )
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(node(_publish_state()))

    assert result["error"] == "knowledge_build_lock_ownership_lost"
    assert calls == []


def test_publish_document_claims_owner_after_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: calls.append("claim") or None,
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: calls.append("status"),
    )

    async def fake_stage(**_kwargs):
        calls.append("stage")
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(
        publish_document_module,
        "publish_staged_knowledge_docs",
        lambda **_kwargs: calls.append("publish") or [],
    )
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(node(_publish_state()))

    assert result["error"] == "knowledge_build_publish_claim_rejected"
    assert calls == ["status", "stage", "claim"]


@pytest.mark.parametrize(
    ("failed_stage", "expected_calls"),
    [
        ("doc_lane_staging", ["status:doc_lane_staging"]),
        (
            "publishing",
            ["status:doc_lane_staging", "stage", "claim", "status:publishing"],
        ),
    ],
)
def test_publish_document_routes_pre_publish_status_failure_to_rollback_state(
    monkeypatch: pytest.MonkeyPatch,
    failed_stage: str,
    expected_calls: list[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: calls.append("claim") or "publish-token",
    )

    def update_status(*_args, **kwargs) -> None:
        stage = str(kwargs.get("stage") or "")
        calls.append(f"status:{stage}")
        if stage == failed_stage:
            raise RuntimeError("runtime store unavailable")

    monkeypatch.setattr(publish_document_module, "update_knowledge_build_status", update_status)

    async def fake_stage(**_kwargs):
        calls.append("stage")
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(
        publish_document_module,
        "publish_staged_knowledge_docs",
        lambda **_kwargs: calls.append("publish") or [],
    )
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(node(_publish_state()))

    assert result == {
        "error": "knowledge_build_publish_failed",
        "cancel_after_rollback": False,
    }
    assert calls == expected_calls


def test_publish_document_passes_claim_token_to_live_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    publish_kwargs: dict[str, object] = {}
    caller_thread_id = get_ident()
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: calls.append("claim") or "publish-token",
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: calls.append(f"status:{kwargs.get('stage')}"),
    )

    async def fake_stage(**_kwargs):
        calls.append("stage")
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    def fake_publish(**kwargs):
        calls.append("publish")
        publish_kwargs.update(kwargs)
        publish_kwargs["thread_id"] = get_ident()
        return ["doc-1"]

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(publish_document_module, "publish_staged_knowledge_docs", fake_publish)
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_merge_preview",
        lambda *args, **kwargs: calls.append("merge_preview"),
    )
    monkeypatch.setattr(
        publish_document_module,
        "upsert_knowledge_build_chapter_progress",
        lambda *args, **kwargs: calls.append("chapter_completed"),
    )
    monkeypatch.setattr(
        publish_document_module,
        "append_knowledge_build_recent_event",
        lambda *args, **kwargs: calls.append("final_event"),
    )

    async def fake_progress(*_args, **_kwargs):
        return None

    monkeypatch.setattr(publish_document_module, "publish_docgen_progress", fake_progress)
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(node(_publish_state()))

    assert result["doc_ids"] == ["doc-1"]
    assert calls[:4] == ["status:doc_lane_staging", "stage", "claim", "status:publishing"]
    assert calls[4] == "publish"
    assert calls[5:] == [
        "merge_preview",
        "chapter_completed",
        "final_event",
        "status:completed",
    ]
    assert publish_kwargs["build_group_id"] == "group-publish"
    assert publish_kwargs["publish_token"] == "publish-token"
    assert publish_kwargs["thread_id"] != caller_thread_id


def test_publish_document_drains_worker_before_propagating_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_started = Event()
    allow_publish_finish = Event()
    publish_finished = Event()
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: "publish-token",
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: None,
    )

    async def fake_stage(**_kwargs):
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    def blocking_publish(**_kwargs):
        publish_started.set()
        assert allow_publish_finish.wait(timeout=5)
        publish_finished.set()
        return ["doc-1"]

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(publish_document_module, "publish_staged_knowledge_docs", blocking_publish)
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    async def run_scenario() -> None:
        node_task = asyncio.create_task(node(_publish_state()))
        assert await asyncio.to_thread(publish_started.wait, 2)

        node_task.cancel()
        await asyncio.sleep(0.05)

        assert node_task.done() is False
        assert publish_finished.is_set() is False

        allow_publish_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await node_task
        assert publish_finished.is_set() is True

    asyncio.run(run_scenario())


def test_publish_document_routes_worker_failure_to_rollback_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: "publish-token",
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: None,
    )

    async def fake_stage(**_kwargs):
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    def failing_publish(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(publish_document_module, "publish_staged_knowledge_docs", failing_publish)
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(node(_publish_state()))

    assert result == {
        "error": "knowledge_build_publish_failed",
        "cancel_after_rollback": False,
    }


def test_publish_document_routes_cancelled_worker_failure_to_rollback_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_started = Event()
    allow_publish_finish = Event()
    monkeypatch.setattr(
        publish_document_module,
        "is_knowledge_build_lock_owner",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        publish_document_module,
        "claim_knowledge_build_publish",
        lambda *args, **kwargs: "publish-token",
    )
    monkeypatch.setattr(
        publish_document_module,
        "update_knowledge_build_status",
        lambda *args, **kwargs: None,
    )

    async def fake_stage(**_kwargs):
        return SimpleNamespace(merged_markdown="# 矩阵", built_paths=[(1, "矩阵")])

    def failing_publish(**_kwargs):
        publish_started.set()
        assert allow_publish_finish.wait(timeout=5)
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(publish_document_module, "stage_knowledge_docs", fake_stage)
    monkeypatch.setattr(publish_document_module, "publish_staged_knowledge_docs", failing_publish)
    node = publish_document_module.build_publish_document_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    async def run_scenario() -> None:
        node_task = asyncio.create_task(node(_publish_state()))
        assert await asyncio.to_thread(publish_started.wait, 2)
        node_task.cancel()
        await asyncio.sleep(0.05)
        assert node_task.done() is False

        allow_publish_finish.set()
        result = await node_task
        assert result == {
            "error": "knowledge_build_publish_failed",
            "cancel_after_rollback": True,
        }

    asyncio.run(run_scenario())


def test_knowledge_graph_rollback_skips_after_owner_fence_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction_kwargs: dict[str, object] = {}
    rollback_calls: list[str] = []

    @contextmanager
    def rejected_transaction(*_args, **kwargs):
        transaction_kwargs.update(kwargs)
        raise RuntimeError("knowledge_build_rollback_owner_lost")
        yield  # pragma: no cover

    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "managed_knowledge_build_owner_transaction",
        rejected_transaction,
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "rollback_docgen_kg_draft_graph_early",
        lambda *args, **kwargs: rollback_calls.append("rollback") or {},
    )
    node = rollback_knowledge_graph_module.build_rollback_knowledge_graph_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(
        node(
            {
                "course_id": COURSE_ID,
                "user_id": USER_ID,
                "build_group_id": "group-stale",
                "kg_draft_early_persist_metrics": {"build_revision_no": 1},
            }
        )
    )

    assert rollback_calls == []
    assert transaction_kwargs["build_group_id"] == "group-stale"
    assert transaction_kwargs["allowed_phases"] == ("active", "publishing_claimed")
    assert result["kg_draft_rollback_metrics"]["skip_reason"] == "rollback_owner_lost"


def test_knowledge_graph_rollback_uses_owner_fenced_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fenced_session = object()
    transaction_kwargs: dict[str, object] = {}
    rollback_sessions: list[object] = []
    stream_events: list[tuple[str, str, dict[str, object]]] = []

    @contextmanager
    def accepted_transaction(*_args, **kwargs):
        transaction_kwargs.update(kwargs)
        yield fenced_session

    def rollback(session, **_kwargs):
        rollback_sessions.append(session)
        return {
            "ok": True,
            "skipped": False,
            "build_revision_no": 2,
            "deleted_unit_count": 1,
        }

    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "managed_knowledge_build_owner_transaction",
        accepted_transaction,
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "rollback_docgen_kg_draft_graph_early",
        rollback,
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "publish_workflow_stream_event",
        lambda course_id, event, payload: stream_events.append((course_id, event, payload)),
    )
    node = rollback_knowledge_graph_module.build_rollback_knowledge_graph_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(
        node(
            {
                "course_id": COURSE_ID,
                "user_id": USER_ID,
                "build_group_id": "group-current",
                "kg_draft_early_persist_metrics": {"build_revision_no": 2},
            }
        )
    )

    assert rollback_sessions == [fenced_session]
    assert transaction_kwargs["build_group_id"] == "group-current"
    assert transaction_kwargs["allowed_phases"] == ("active", "publishing_claimed")
    assert result["kg_draft_rollback_metrics"]["deleted_unit_count"] == 1
    assert stream_events[0][1] == "graph_delta"


def test_knowledge_graph_rollback_keeps_database_publish_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rollback_calls: list[str] = []

    @contextmanager
    def accepted_transaction(*_args, **_kwargs):
        yield object()

    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "managed_knowledge_build_owner_transaction",
        accepted_transaction,
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [SimpleNamespace(build_session_id="build-published")],
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "rollback_docgen_kg_draft_graph_early",
        lambda *args, **kwargs: rollback_calls.append("rollback") or {},
    )
    node = rollback_knowledge_graph_module.build_rollback_knowledge_graph_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    result = asyncio.run(
        node(
            {
                "course_id": COURSE_ID,
                "user_id": USER_ID,
                "build_group_id": "group-current",
                "build_session_id": "build-published",
                "kg_draft_early_persist_metrics": {"build_revision_no": 2},
            }
        )
    )

    assert rollback_calls == []
    assert result["kg_draft_rollback_metrics"]["skip_reason"] == "document_already_published"


def test_knowledge_graph_rollback_rethrows_cancellation_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import app.shared.infra.database as database

    rollback_calls: list[str] = []
    course_scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    monkeypatch.setattr(build_store, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(build_store, "get_runtime_data_dir", lambda: tmp_path)

    @contextmanager
    def fake_managed_session():
        yield object()

    monkeypatch.setattr(database, "managed_session", fake_managed_session)
    assert build_store.acquire_knowledge_build_lock(
        COURSE_ID,
        build_store.KnowledgeBuildLock(
            requested_at=datetime.now(timezone.utc),
            build_group_id="group-current",
        ),
        course_scope=course_scope,
    )
    assert build_store.request_knowledge_build_cancellation(
        COURSE_ID,
        build_group_id="group-current",
        course_scope=course_scope,
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "get_current_published_docs",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        rollback_knowledge_graph_module,
        "rollback_docgen_kg_draft_graph_early",
        lambda *args, **kwargs: rollback_calls.append("rollback")
        or {"ok": True, "skipped": False},
    )
    node = rollback_knowledge_graph_module.build_rollback_knowledge_graph_node(
        context=SimpleNamespace(get_logger=lambda: _NoopNodeLogger())
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            node(
                {
                    "course_id": COURSE_ID,
                    "user_id": USER_ID,
                    "build_group_id": "group-current",
                    "cancel_after_rollback": True,
                    "kg_draft_early_persist_metrics": {"build_revision_no": 2},
                }
            )
        )

    assert rollback_calls == ["rollback"]


def test_build_lock_heartbeat_cancels_owner_before_lease_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OwnerTask:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    owner_task = _OwnerTask()
    monotonic_values = iter([0.0, 11.0])

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(common_build_lifecycle, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(common_build_lifecycle.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(common_build_lifecycle, "BUILD_LOCK_RENEW_DEADLINE_SECONDS", 10.0)
    monkeypatch.setattr(
        common_build_lifecycle,
        "renew_knowledge_build_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    asyncio.run(
        common_build_lifecycle.maintain_knowledge_build_lock_lease(
            course_id=COURSE_ID,
            build_group_id="group-heartbeat",
            course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
            owner_task=owner_task,  # type: ignore[arg-type]
        )
    )

    assert owner_task.cancelled is True
    assert (
        common_build_lifecycle.BUILD_LOCK_RENEW_DEADLINE_SECONDS
        < common_build_lifecycle.STALE_BUILD_LOCK_TTL.total_seconds()
    )


def test_build_lock_heartbeat_observes_persisted_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OwnerTask:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    owner_task = _OwnerTask()
    cancellation_writes: list[str] = []
    now = datetime.now(timezone.utc)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(common_build_lifecycle.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(common_build_lifecycle, "renew_knowledge_build_lock", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-cancelled",
            cancel_requested_at=now,
        ),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_knowledge_build_runtime_cancelled",
        lambda _course_id, *, build_group_id, **_kwargs: cancellation_writes.append(build_group_id),
    )

    asyncio.run(
        common_build_lifecycle.maintain_knowledge_build_lock_lease(
            course_id=COURSE_ID,
            build_group_id="group-cancelled",
            course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
            owner_task=owner_task,  # type: ignore[arg-type]
        )
    )

    assert cancellation_writes == ["group-cancelled"]
    assert owner_task.cancelled is True


def test_build_lock_heartbeat_marks_published_docgen_completed_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OwnerTask:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    owner_task = _OwnerTask()
    marker_calls: list[dict[str, object]] = []
    now = datetime.now(timezone.utc)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(common_build_lifecycle.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(common_build_lifecycle, "renew_knowledge_build_lock", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-published",
            cancel_requested_at=now,
            phase="published",
            publish_started_at=now,
            publish_completed_at=now,
            publish_token="publish-token",
        ),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_knowledge_build_runtime_cancelled",
        lambda _course_id, **kwargs: marker_calls.append(dict(kwargs)),
    )

    asyncio.run(
        common_build_lifecycle.maintain_knowledge_build_lock_lease(
            course_id=COURSE_ID,
            build_group_id="group-published",
            course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
            owner_task=owner_task,  # type: ignore[arg-type]
        )
    )

    assert marker_calls[0]["docgen_published"] is True
    assert owner_task.cancelled is True


def test_build_lock_heartbeat_retries_when_read_confirms_same_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OwnerTask:
        cancel_count = 0

        def cancel(self) -> None:
            self.cancel_count += 1

    owner_task = _OwnerTask()
    now = datetime.now(timezone.utc)
    renew_calls: list[str] = []
    lock_reads = iter(
        [
            build_store.KnowledgeBuildLock(
                requested_at=now,
                build_group_id="group-heartbeat",
            ),
            None,
        ]
    )

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(common_build_lifecycle.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(common_build_lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        common_build_lifecycle,
        "renew_knowledge_build_lock",
        lambda *args, **kwargs: renew_calls.append("renew") or False,
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: next(lock_reads),
    )

    asyncio.run(
        common_build_lifecycle.maintain_knowledge_build_lock_lease(
            course_id=COURSE_ID,
            build_group_id="group-heartbeat",
            course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
            owner_task=owner_task,  # type: ignore[arg-type]
        )
    )

    assert renew_calls == ["renew", "renew"]
    assert owner_task.cancel_count == 1


def test_build_lock_heartbeat_retries_transient_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OwnerTask:
        cancel_count = 0

        def cancel(self) -> None:
            self.cancel_count += 1

    owner_task = _OwnerTask()
    now = datetime.now(timezone.utc)
    renew_calls: list[str] = []
    read_calls: list[str] = []
    lock_reads = iter(
        [
            RuntimeError("database unavailable"),
            build_store.KnowledgeBuildLock(
                requested_at=now,
                build_group_id="group-heartbeat",
            ),
            None,
        ]
    )

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_sleep(_delay: float) -> None:
        return None

    def read_lock(*_args, **_kwargs):
        read_calls.append("read")
        result = next(lock_reads)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(common_build_lifecycle.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(common_build_lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        common_build_lifecycle,
        "renew_knowledge_build_lock",
        lambda *args, **kwargs: renew_calls.append("renew") or False,
    )
    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_lock", read_lock)

    asyncio.run(
        common_build_lifecycle.maintain_knowledge_build_lock_lease(
            course_id=COURSE_ID,
            build_group_id="group-heartbeat",
            course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
            owner_task=owner_task,  # type: ignore[arg-type]
        )
    )

    assert renew_calls == ["renew", "renew", "renew"]
    assert read_calls == ["read", "read", "read"]
    assert owner_task.cancel_count == 1


def test_cancel_knowledge_build_persists_request_before_cancelling_local_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Linear Algebra")
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(
        docgen_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_group_id="group-cancel",
            status="running",
            stage="generating_chapters",
        )
    )
    events: list[str] = []

    class _Registry:
        async def cancel_matching(self, *, kind: str, course_id: str, name: str) -> int:
            events.append(f"cancel:{kind}:{course_id}:{name}")
            return 1

    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-cancel",
        ),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "request_knowledge_build_cancellation",
        lambda *args, **kwargs: events.append("persist-cancel") or True,
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_knowledge_build_runtime_cancelled",
        lambda *args, **kwargs: events.append("write-cancelled-runtime"),
    )

    result = asyncio.run(
        common_build_lifecycle.cancel_knowledge_build(
            object(),  # type: ignore[arg-type]
            course=course,
            user_id=USER_ID,
            background_task_registry=_Registry(),
        )
    )

    assert events[:2] == ["persist-cancel", "write-cancelled-runtime"]
    assert set(events[2:]) == {
        f"cancel:knowledge.build.docs:{COURSE_ID}:knowledge.build.docs:{COURSE_ID}:group-cancel",
        f"cancel:knowledge.build.graph:{COURSE_ID}:knowledge.build.graph:{COURSE_ID}:group-cancel",
    }
    assert result.cancelled_task_count == 2


def test_cancel_published_build_keeps_docgen_and_plan_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Linear Algebra")
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-published",
        docgen_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_group_id="group-published",
            status="completed",
            stage="completed",
            confirmed_plan_id="plan-1",
        ),
        graph_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_kind="graph",
            build_group_id="group-published",
            status="running",
            stage="graph_docs_sync",
        ),
    )
    lane_updates: list[dict[str, object]] = []
    plan_updates: list[dict[str, object]] = []

    class _Registry:
        async def cancel_matching(self, **_kwargs) -> int:
            return 0

    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-published",
            phase="published",
            publish_started_at=now,
            publish_completed_at=now,
            publish_token="publish-token",
        ),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "request_knowledge_build_cancellation",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "update_knowledge_build_lane_status",
        lambda *args, **kwargs: lane_updates.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_confirmed_build_plan_status",
        lambda *args, **kwargs: plan_updates.append(dict(kwargs)),
    )

    result = asyncio.run(
        common_build_lifecycle.cancel_knowledge_build(
            object(),  # type: ignore[arg-type]
            course=course,
            user_id=USER_ID,
            background_task_registry=_Registry(),
        )
    )

    assert result.cancelled_task_count == 0
    assert [update["lane"] for update in lane_updates] == ["graph"]
    assert lane_updates[0]["status"] == "cancelled"
    assert plan_updates == [
        {
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "plan_id": "plan-1",
            "status": "completed",
        }
    ]


@pytest.mark.parametrize("retain_published_lock", [True, False])
def test_cancel_knowledge_build_rechecks_publish_after_request(
    monkeypatch: pytest.MonkeyPatch,
    retain_published_lock: bool,
) -> None:
    now = datetime.now(timezone.utc)
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Linear Algebra")
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-publish-race",
        docgen_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_group_id="group-publish-race",
            build_session_id="build-session-publish-race",
            status="publishing",
            stage="publishing",
            confirmed_plan_id="plan-1",
        ),
        graph_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_kind="graph",
            build_group_id="group-publish-race",
            status="running",
            stage="graph_docs_sync",
        ),
    )
    publish_completed = False
    lock_reads: list[str] = []
    database_receipt_reads: list[str] = []
    lane_updates: list[dict[str, object]] = []
    plan_updates: list[dict[str, object]] = []

    def read_lock(*_args, **_kwargs):
        lock_reads.append("published" if publish_completed else "active")
        if publish_completed and not retain_published_lock:
            return None
        if publish_completed:
            return build_store.KnowledgeBuildLock(
                requested_at=now,
                build_group_id="group-publish-race",
                phase="published",
                publish_started_at=now,
                publish_completed_at=now,
                publish_token="publish-token",
                cancel_requested_at=now,
            )
        return build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-publish-race",
        )

    def request_cancellation(*_args, **_kwargs) -> bool:
        nonlocal publish_completed
        publish_completed = True
        return True

    @contextmanager
    def fake_receipt_session():
        yield object()

    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_lock", read_lock)
    monkeypatch.setattr(common_build_lifecycle, "request_knowledge_build_cancellation", request_cancellation)
    monkeypatch.setattr(common_build_lifecycle, "managed_session", fake_receipt_session)
    monkeypatch.setattr(
        common_build_lifecycle,
        "get_docs_by_course",
        lambda _session, course_id: database_receipt_reads.append(course_id)
        or [SimpleNamespace(build_session_id="build-session-publish-race")],
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "update_knowledge_build_lane_status",
        lambda *args, **kwargs: lane_updates.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_confirmed_build_plan_status",
        lambda *args, **kwargs: plan_updates.append(dict(kwargs)),
    )

    result = asyncio.run(
        common_build_lifecycle.cancel_knowledge_build(
            object(),  # type: ignore[arg-type]
            course=course,
            user_id=USER_ID,
        )
    )

    assert result.cancelled_task_count == 0
    assert lock_reads == ["active", "published"]
    assert database_receipt_reads == ([] if retain_published_lock else [COURSE_ID])
    assert [(update["lane"], update["status"]) for update in lane_updates] == [
        ("docgen", "completed"),
        ("graph", "cancelled"),
    ]
    assert lane_updates[0]["error_message"] is None
    assert plan_updates[-1]["status"] == "completed"


def test_cancel_knowledge_build_preserves_docgen_when_publish_receipt_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Linear Algebra")
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-unknown-receipt",
        docgen_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_group_id="group-unknown-receipt",
            build_session_id="build-session-unknown-receipt",
            status="publishing",
            stage="publishing",
            confirmed_plan_id="plan-1",
        ),
        graph_runtime=build_store.KnowledgeBuildRuntimeStatus(
            requested_at=now,
            build_kind="graph",
            build_group_id="group-unknown-receipt",
            status="running",
            stage="graph_docs_sync",
        ),
    )
    lock_reads = iter(
        [
            build_store.KnowledgeBuildLock(
                requested_at=now,
                build_group_id="group-unknown-receipt",
            ),
            None,
        ]
    )
    lane_updates: list[dict[str, object]] = []
    plan_updates: list[dict[str, object]] = []
    cancelled_tasks: list[str] = []

    class _Registry:
        async def cancel_matching(self, *, kind: str, **_kwargs) -> int:
            cancelled_tasks.append(kind)
            return 1

    @contextmanager
    def fake_receipt_session():
        yield object()

    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_lock", lambda *args, **kwargs: next(lock_reads))
    monkeypatch.setattr(common_build_lifecycle, "request_knowledge_build_cancellation", lambda *args, **kwargs: True)
    monkeypatch.setattr(common_build_lifecycle, "managed_session", fake_receipt_session)
    monkeypatch.setattr(
        common_build_lifecycle,
        "get_docs_by_course",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "update_knowledge_build_lane_status",
        lambda *args, **kwargs: lane_updates.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "mark_confirmed_build_plan_status",
        lambda *args, **kwargs: plan_updates.append(dict(kwargs)),
    )

    result = asyncio.run(
        common_build_lifecycle.cancel_knowledge_build(
            object(),  # type: ignore[arg-type]
            course=course,
            user_id=USER_ID,
            background_task_registry=_Registry(),
        )
    )

    assert result.cancelled_task_count == 2
    assert [(update["lane"], update["status"]) for update in lane_updates] == [
        ("graph", "cancelled")
    ]
    assert plan_updates == []
    assert set(cancelled_tasks) == {"knowledge.build.docs", "knowledge.build.graph"}


@pytest.mark.parametrize("failure_mode", ["result", "exception"])
def test_docgen_background_preserves_published_docs_when_downstream_graph_fails(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    import app.workflows.digest as digest_workflows
    from app.shared.infra.workflow import err_result
    from app.workflows.digest.kg_doc_sync.lib import prefetch as prefetch_module

    now = datetime.now(timezone.utc)
    docgen_writes: list[dict[str, object]] = []
    graph_writes: list[dict[str, object]] = []
    plan_statuses: list[str] = []
    staging_clears: list[str] = []
    releases: list[tuple[str, str]] = []

    async def fake_heartbeat(**_kwargs) -> None:
        await asyncio.Future()

    async def fake_workflow(**_kwargs):
        if failure_mode == "exception":
            raise RuntimeError("kg crashed after publish")
        return err_result("kg_sync_failed", "kg failed after publish")

    @contextmanager
    def fake_trace(**_kwargs):
        yield None

    monkeypatch.setattr(
        build_lifecycle,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )
    monkeypatch.setattr(build_lifecycle, "_new_build_session_id", lambda: "build-session-published")
    monkeypatch.setattr(build_lifecycle, "langsmith_trace", fake_trace)
    monkeypatch.setattr(build_lifecycle, "maintain_knowledge_build_lock_lease", fake_heartbeat)
    monkeypatch.setattr(build_lifecycle, "_still_owns_build_lock", lambda **_kwargs: True)
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-published",
            phase="published",
            publish_started_at=now,
            publish_completed_at=now,
            publish_token="publish-token",
        ),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_load_confirmed_plan_payload",
        lambda **_kwargs: (
            SimpleNamespace(planner_session_id="planner-1", digest_mode="systematic"),
            {"plan": "confirmed"},
        ),
    )
    monkeypatch.setattr(build_lifecycle, "_confirmed_plan_model_override", lambda _payload: None)
    monkeypatch.setattr(
        build_lifecycle,
        "_mark_confirmed_plan_status",
        lambda **kwargs: plan_statuses.append(str(kwargs["status"])),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_write_docgen_status",
        lambda *args, **kwargs: docgen_writes.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_write_graph_status",
        lambda *args, **kwargs: graph_writes.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_clear_docgen_staging_safely",
        lambda *args, **kwargs: staging_clears.append("clear"),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "release_knowledge_build_lock",
        lambda course_id, *, build_group_id, **_kwargs: releases.append((course_id, build_group_id)) or True,
    )
    monkeypatch.setattr(digest_workflows, "run_docgen_workflow", fake_workflow)
    monkeypatch.setattr(prefetch_module, "cancel_docgen_kg_prefetch", lambda **_kwargs: None)

    asyncio.run(
        build_lifecycle.run_docgen_background(
            course_id=COURSE_ID,
            course_name="Linear Algebra",
            file_ids=["file-ready"],
            prompt="build",
            requested_at=now,
            build_group_id="group-published",
            confirmed_plan_id="plan-1",
            user_id=USER_ID,
        )
    )

    assert [write["status"] for write in docgen_writes] == ["running", "completed"]
    assert graph_writes[-1]["status"] == "failed"
    assert plan_statuses == ["building", "completed"]
    assert staging_clears == ["clear"]
    assert releases == [(COURSE_ID, "group-published")]


def test_docgen_background_marks_completed_when_cancelled_publish_drain_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workflows.digest as digest_workflows
    from app.workflows.digest.kg_doc_sync.lib import prefetch as prefetch_module

    now = datetime.now(timezone.utc)
    publish_started = Event()
    allow_publish_finish = Event()
    publish_finished = Event()
    docgen_writes: list[dict[str, object]] = []
    graph_writes: list[dict[str, object]] = []
    plan_statuses: list[str] = []
    staging_clears: list[str] = []
    releases: list[tuple[str, str]] = []

    async def fake_heartbeat(**_kwargs) -> None:
        await asyncio.Future()

    async def publish_worker() -> None:
        publish_started.set()
        assert await asyncio.to_thread(allow_publish_finish.wait, 2)
        publish_finished.set()

    async def fake_workflow(**_kwargs):
        worker_task = asyncio.create_task(publish_worker())
        try:
            await asyncio.shield(worker_task)
        except asyncio.CancelledError:
            await worker_task
            raise
        raise AssertionError("workflow should have been cancelled during publish")

    @contextmanager
    def fake_trace(**_kwargs):
        yield None

    def read_lock(*_args, **_kwargs) -> build_store.KnowledgeBuildLock:
        if publish_finished.is_set():
            return build_store.KnowledgeBuildLock(
                requested_at=now,
                build_group_id="group-publish-cancel",
                phase="published",
                publish_started_at=now,
                publish_completed_at=now,
                publish_token="publish-token",
            )
        return build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="group-publish-cancel",
        )

    monkeypatch.setattr(
        build_lifecycle,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )
    monkeypatch.setattr(build_lifecycle, "_new_build_session_id", lambda: "build-session-publish-cancel")
    monkeypatch.setattr(build_lifecycle, "langsmith_trace", fake_trace)
    monkeypatch.setattr(build_lifecycle, "maintain_knowledge_build_lock_lease", fake_heartbeat)
    monkeypatch.setattr(build_lifecycle, "_still_owns_build_lock", lambda **_kwargs: True)
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_lock", read_lock)
    monkeypatch.setattr(
        build_lifecycle,
        "_load_confirmed_plan_payload",
        lambda **_kwargs: (
            SimpleNamespace(planner_session_id="planner-1", digest_mode="systematic"),
            {"plan": "confirmed"},
        ),
    )
    monkeypatch.setattr(build_lifecycle, "_confirmed_plan_model_override", lambda _payload: None)
    monkeypatch.setattr(
        build_lifecycle,
        "_mark_confirmed_plan_status",
        lambda **kwargs: plan_statuses.append(str(kwargs["status"])),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_write_docgen_status",
        lambda *args, **kwargs: docgen_writes.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_write_graph_status",
        lambda *args, **kwargs: graph_writes.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "_clear_docgen_staging_safely",
        lambda *args, **kwargs: staging_clears.append("clear"),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "release_knowledge_build_lock",
        lambda course_id, *, build_group_id, **_kwargs: releases.append((course_id, build_group_id)) or True,
    )
    monkeypatch.setattr(digest_workflows, "run_docgen_workflow", fake_workflow)
    monkeypatch.setattr(prefetch_module, "cancel_docgen_kg_prefetch", lambda **_kwargs: None)

    async def run_scenario() -> None:
        task = asyncio.create_task(
            build_lifecycle.run_docgen_background(
                course_id=COURSE_ID,
                course_name="Linear Algebra",
                file_ids=["file-ready"],
                prompt="build",
                requested_at=now,
                build_group_id="group-publish-cancel",
                confirmed_plan_id="plan-1",
                user_id=USER_ID,
            )
        )
        assert await asyncio.to_thread(publish_started.wait, 2)

        task.cancel()
        await asyncio.sleep(0.05)
        assert task.done() is False
        assert publish_finished.is_set() is False

        allow_publish_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_scenario())

    assert publish_finished.is_set() is True
    assert [write["status"] for write in docgen_writes] == ["running", "completed"]
    assert graph_writes[-1]["status"] == "cancelled"
    assert plan_statuses == ["building", "completed"]
    assert staging_clears == ["clear"]
    assert releases == [(COURSE_ID, "group-publish-cancel")]


def test_cancel_knowledge_build_does_not_interrupt_maintenance_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Linear Algebra")
    now = datetime.now(timezone.utc)
    cancellation_requests: list[str] = []
    monkeypatch.setattr(common_build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        common_build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id="knowledge-clear:owner",
        ),
    )
    monkeypatch.setattr(
        common_build_lifecycle,
        "request_knowledge_build_cancellation",
        lambda *args, **kwargs: cancellation_requests.append("cancel") or True,
    )

    result = asyncio.run(
        common_build_lifecycle.cancel_knowledge_build(
            object(),  # type: ignore[arg-type]
            course=course,
            user_id=USER_ID,
        )
    )

    assert result.cancelled_task_count == 0
    assert cancellation_requests == []


def test_clear_course_knowledge_rejects_active_build_lock(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_course_and_files(session)
    monkeypatch.setattr(common_cleanup, "acquire_knowledge_build_lock", lambda *args, **kwargs: False)

    with pytest.raises(CourseBuildLockConflictError):
        common_cleanup.clear_course_knowledge(session, course_id=COURSE_ID)


def test_clear_course_knowledge_holds_maintenance_lock_through_artifact_cleanup(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_course_and_files(session)
    events: list[str] = []
    monkeypatch.setattr(
        common_cleanup,
        "acquire_knowledge_build_lock",
        lambda *args, **kwargs: events.append("acquire") or True,
    )

    @contextmanager
    def fake_lease(**_kwargs):
        events.append("heartbeat-start")
        try:
            yield SimpleNamespace(lost=False)
        finally:
            events.append("heartbeat-stop")

    monkeypatch.setattr(
        common_cleanup,
        "maintain_synchronous_knowledge_build_lock_lease",
        fake_lease,
    )
    monkeypatch.setattr(
        common_cleanup,
        "clear_knowledge_runtime_artifacts",
        lambda *args, **kwargs: events.append("clear-runtime"),
    )
    monkeypatch.setattr(
        common_cleanup,
        "release_knowledge_build_lock",
        lambda *args, **kwargs: events.append("release") or True,
    )

    common_cleanup.clear_course_knowledge(session, course_id=COURSE_ID)

    assert events == [
        "acquire",
        "heartbeat-start",
        "clear-runtime",
        "heartbeat-stop",
        "release",
    ]


def test_synchronous_maintenance_lease_guard_renews_until_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renewed_twice = Event()
    renewals: list[str] = []

    def fake_renew(_course_id: str, *, build_group_id: str, **_kwargs) -> bool:
        renewals.append(build_group_id)
        if len(renewals) >= 2:
            renewed_twice.set()
        return True

    monkeypatch.setattr(common_build_lifecycle, "renew_knowledge_build_lock", fake_renew)
    monkeypatch.setattr(common_build_lifecycle, "BUILD_LOCK_RENEW_INTERVAL_SECONDS", 0.01)

    with common_build_lifecycle.maintain_synchronous_knowledge_build_lock_lease(
        course_id=COURSE_ID,
        build_group_id="knowledge-clear:test",
        course_scope=build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID),
    ) as lease:
        assert renewed_twice.wait(timeout=1.0)
        assert lease.lost is False

    assert renewals[:2] == ["knowledge-clear:test", "knowledge-clear:test"]


def test_clear_course_knowledge_stops_when_maintenance_lease_is_lost(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_course_and_files(session)
    events: list[str] = []
    monkeypatch.setattr(
        common_cleanup,
        "acquire_knowledge_build_lock",
        lambda *args, **kwargs: events.append("acquire") or True,
    )

    @contextmanager
    def lost_lease(**_kwargs):
        events.append("heartbeat-start")
        try:
            yield SimpleNamespace(lost=True)
        finally:
            events.append("heartbeat-stop")

    monkeypatch.setattr(
        common_cleanup,
        "maintain_synchronous_knowledge_build_lock_lease",
        lost_lease,
    )
    monkeypatch.setattr(
        common_cleanup,
        "clear_knowledge_runtime_artifacts",
        lambda *args, **kwargs: events.append("clear-runtime"),
    )
    monkeypatch.setattr(
        common_cleanup,
        "release_knowledge_build_lock",
        lambda *args, **kwargs: events.append("release") or True,
    )

    with pytest.raises(CourseBuildLockConflictError):
        common_cleanup.clear_course_knowledge(session, course_id=COURSE_ID)

    assert events == ["acquire", "heartbeat-start", "heartbeat-stop", "release"]


@pytest.mark.parametrize(
    ("build_group_id", "cancel_requested"),
    [
        ("knowledge-clear:owner", False),
        ("group-cancelled", True),
    ],
)
def test_runtime_fallback_ignores_non_runnable_build_locks(
    monkeypatch: pytest.MonkeyPatch,
    build_group_id: str,
    cancel_requested: bool,
) -> None:
    now = datetime.now(timezone.utc)
    status_updates: list[dict[str, object]] = []
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_lock",
        lambda *args, **kwargs: build_store.KnowledgeBuildLock(
            requested_at=now,
            build_group_id=build_group_id,
            cancel_requested_at=now if cancel_requested else None,
        ),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "update_knowledge_build_lane_status",
        lambda *args, **kwargs: status_updates.append(dict(kwargs)),
    )

    result = build_lifecycle._resolve_runtime_build_status(course_id=COURSE_ID)

    assert result is None
    assert status_updates == []


def test_runtime_preview_metrics_and_build_runtime_result(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    docgen_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        build_group_id="group-1",
        build_session_id="build-1",
        status="running",
        stage="generating_chapters",
        progress_pct=42,
        current_stage_description="正在写章节",
        digest_mode="systematic",
        plan="两章计划",
        sample_nodes=[{"name": "Matrix", "type": "concept"}, {"name": "", "type": "ignored"}],
        sample_cards=[{"title": "Card", "summary": "Summary", "card_type": ""}, {"title": "", "summary": "Ignored"}],
        chapter_progress=[{"chapter_index": 1, "title": "矩阵", "status": "drafting", "source_count": 2}],
        chapter_previews=[{"chapter_index": 1, "title": "矩阵", "status": "generated", "excerpt": "正文"}],
        recent_events=[{"stage": "drafting", "summary": "章节已生成", "created_at": now}],
        metrics={"staged_chapter_count": 1},
    )
    graph_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="graph",
        build_group_id="group-1",
        status="running",
        stage="graph_docs_sync",
        metrics={"doc_sync_section_count": 3, "doc_sync_unit_changes": 2},
    )
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(
        build_group_id="group-1",
        docgen_runtime=docgen_status,
        graph_runtime=graph_status,
    )
    manifest = SimpleNamespace(
        chapter_titles=["Manifest A", "Manifest B"],
        updated_at=now,
        version_no=3,
        source_file_ids=["file-ready"],
        prompt="manifest prompt",
    )
    store = _TextStore({scope.knowledge_build_prefix() + "merged_knowledge_base.md": "# Draft\n\n正文"})
    monkeypatch.setattr(build_lifecycle, "resolve_course_storage_scope", lambda *args, **kwargs: scope)
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: store)
    monkeypatch.setattr(build_lifecycle, "run_store_sync", lambda func, *args, default=None, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(build_lifecycle, "_resolve_current_published_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(
        build_lifecycle,
        "build_token_summary",
        lambda **_kwargs: SimpleNamespace(
            total_calls=4,
            failed_call_count=1,
            avg_latency_ms=125.5,
            call_count_by_lane={"docgen": 3, "(unknown_lane)": 1},
        ),
    )

    preview = build_lifecycle._build_runtime_preview(
        build_status=docgen_status,
        draft_markdown="# Draft Title\n\n正文",
        manifest=manifest,
    )
    metrics = build_lifecycle._build_runtime_metrics(build_status=docgen_status)
    result = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)

    assert preview is not None
    assert preview.sample_nodes[0].name == "Matrix"
    assert preview.sample_cards[0].card_type == "topic"
    assert preview.latest_chapter_titles == ["Manifest A", "Manifest B"]
    assert preview.draft_excerpt.startswith("# Draft Title")
    assert metrics is not None
    assert metrics.llm_total_calls == 4
    assert metrics.call_count_by_lane == {"docgen": 3}
    assert result.build_group_id == "group-1"
    assert result.docs_ready is True
    assert result.graph_status == "running"
    assert result.graph_unhealthy is False
    assert result.training_unlocked is False
    assert result.aggregate is not None
    assert result.docgen is not None
    assert result.docgen.status == "running"
    assert result.docgen_metrics is not None
    assert result.graph_metrics.doc_sync_section_count == 3
    assert result.docgen_preview is not None
    assert result.docgen_preview.draft_excerpt.startswith("# Draft")


def test_build_runtime_training_unlocks_on_graph_terminal_states(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    docgen_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        build_group_id="group-terminal",
        status="completed",
        stage="completed",
        progress_pct=100,
    )
    manifest = SimpleNamespace(
        chapter_titles=["Published A"],
        updated_at=now,
        version_no=1,
        source_file_ids=["file-ready"],
        prompt="manifest prompt",
    )
    store = _TextStore({scope.knowledge_build_prefix() + "merged_knowledge_base.md": "# Draft\n\n正文"})

    monkeypatch.setattr(build_lifecycle, "resolve_course_storage_scope", lambda *args, **kwargs: scope)
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: store)
    monkeypatch.setattr(build_lifecycle, "run_store_sync", lambda func, *args, default=None, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(build_lifecycle, "_resolve_current_published_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(
        build_lifecycle,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )

    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-terminal",
            docgen_runtime=docgen_status,
            graph_runtime=None,
        ),
    )
    skipped = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)
    assert skipped.docs_ready is True
    assert skipped.graph_status == "skipped"
    assert skipped.graph_unhealthy is False
    assert skipped.training_unlocked is True

    graph_completed = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="graph",
        build_group_id="group-terminal",
        status="completed",
        stage="completed",
        progress_pct=100,
    )
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-terminal",
            docgen_runtime=docgen_status,
            graph_runtime=graph_completed,
        ),
    )
    completed = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)
    assert completed.docs_ready is True
    assert completed.graph_status == "completed"
    assert completed.graph_unhealthy is False
    assert completed.training_unlocked is True

    graph_partial = graph_completed.model_copy(
        update={"status": "partial_failed", "stage": "partial_failed", "error_message": "kg_doc_sync_partial_failed"}
    )
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-terminal",
            docgen_runtime=docgen_status,
            graph_runtime=graph_partial,
        ),
    )
    partial = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)
    assert partial.docs_ready is True
    assert partial.graph_status == "partial_failed"
    assert partial.graph_unhealthy is False
    assert partial.training_unlocked is True

    graph_failed = graph_completed.model_copy(update={"status": "failed", "stage": "failed", "error_message": "boom"})
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-terminal",
            docgen_runtime=docgen_status,
            graph_runtime=graph_failed,
        ),
    )
    failed = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)
    assert failed.docs_ready is True
    assert failed.graph_status == "failed"
    assert failed.graph_unhealthy is True
    assert failed.training_unlocked is False

    graph_cancelled = graph_completed.model_copy(
        update={"status": "cancelled", "stage": "cancelled", "error_message": "build_cancelled"}
    )
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-terminal",
            docgen_runtime=docgen_status,
            graph_runtime=graph_cancelled,
        ),
    )
    cancelled = build_lifecycle.get_knowledge_build_runtime_result(course_id=COURSE_ID, course_scope=scope)
    assert cancelled.docs_ready is True
    assert cancelled.graph_status == "cancelled"
    assert cancelled.graph_unhealthy is True
    assert cancelled.training_unlocked is False


def test_build_runtime_backfills_graph_status_from_latest_sync_run(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    docgen_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        build_group_id="group-sync",
        status="completed",
        stage="completed",
        progress_pct=100,
    )
    manifest = SimpleNamespace(
        chapter_titles=["Published A"],
        updated_at=now,
        version_no=3,
        source_file_ids=["file-ready"],
        prompt="manifest prompt",
    )
    session.add(
        KnowledgeGraphSyncRun(
            course_id=COURSE_ID,
            build_session_id="build-sync",
            doc_version_no=3,
            graph_revision_no=2,
            status="completed",
            metrics_json=json.dumps(
                {
                    "section_count": 5,
                    "unit_change_count": 8,
                    "edge_change_count": 13,
                    "source_ref_count": 21,
                    "elapsed_ms": 3400,
                },
                ensure_ascii=False,
            ),
            started_at=now,
            finished_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    store = _TextStore({scope.knowledge_build_prefix() + "merged_knowledge_base.md": "# Draft\n\n正文"})
    monkeypatch.setattr(build_lifecycle, "resolve_course_storage_scope", lambda *args, **kwargs: scope)
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: store)
    monkeypatch.setattr(build_lifecycle, "run_store_sync", lambda func, *args, default=None, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(build_lifecycle, "_resolve_current_published_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-sync",
            docgen_runtime=docgen_status,
            graph_runtime=None,
        ),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=True)),
    )

    result = build_lifecycle.get_knowledge_build_runtime_result(session, course_id=COURSE_ID, course_scope=scope)

    assert result.graph_status == "completed"
    assert result.training_unlocked is True
    assert result.graph is not None
    assert result.graph.status == "completed"
    assert result.graph_metrics.doc_sync_section_count == 5
    assert result.graph_metrics.doc_sync_unit_changes == 8
    assert result.graph_metrics.doc_sync_edge_changes == 13
    assert result.graph_metrics.source_ref_count == 21
    assert result.graph_metrics.revision_no == 2
    assert result.graph_metrics.last_synced_doc_version_no == 3


def test_build_runtime_uses_committed_docs_when_manifest_projection_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    _seed_course_and_files(session)
    now = datetime.now(timezone.utc)
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    session.add(
        KnowledgeDocument(
            course_id=COURSE_ID,
            chapter_index=1,
            title="矩阵",
            markdown_content="# 矩阵",
            markdown_path=(
                f"{scope.namespace}/knowledge_markdowns/versions/"
                "v0001/token-hash/chapter_001.md"
            ),
            source_file_ids='["file-ready"]',
            version_no=1,
            build_session_id="build-published",
            is_current=True,
            status="published",
            published_at=now,
        )
    )
    session.commit()
    docgen_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        build_group_id="group-published",
        build_session_id="build-published",
        status="completed",
        stage="completed",
        prompt="published prompt",
        progress_pct=100,
    )
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: _TextStore())
    monkeypatch.setattr(
        build_lifecycle,
        "run_store_sync",
        lambda func, *args, default=None, **kwargs: func(*args, **kwargs),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("manifest store unavailable")),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "read_knowledge_build_runtime",
        lambda *args, **kwargs: build_store.KnowledgeBuildRuntimeEnvelope(
            build_group_id="group-published",
            docgen_runtime=docgen_status,
        ),
    )
    monkeypatch.setattr(
        build_lifecycle,
        "get_settings",
        lambda: SimpleNamespace(knowledge_graph=SimpleNamespace(sync_after_docgen=False)),
    )

    result = build_lifecycle.get_knowledge_build_runtime_result(
        session,
        course_id=COURSE_ID,
        course_scope=scope,
    )

    assert result.docs_ready is True
    assert result.graph_status == "skipped"
    assert result.training_unlocked is True


def test_get_docgen_result_assembles_published_draft_and_runtime(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    now = datetime.now(timezone.utc)
    scope = build_course_storage_scope(user_id=USER_ID, course_id=COURSE_ID)
    docgen_status = build_store.KnowledgeBuildRuntimeStatus(
        requested_at=now,
        build_kind="docgen",
        build_group_id="group-2",
        build_session_id="build-2",
        status="running",
        stage="drafting",
        draft_available=True,
        draft_updated_at=now,
        planner_session_id="planner-1",
        confirmed_plan_id="plan-1",
        digest_mode="sprint",
    )
    runtime = build_store.KnowledgeBuildRuntimeEnvelope(build_group_id="group-2", docgen_runtime=docgen_status)
    manifest = SimpleNamespace(
        chapter_titles=["Published A"],
        updated_at=now,
        version_no=4,
        source_file_ids=["file-ready"],
        prompt="published prompt",
    )
    store = _TextStore({scope.knowledge_build_prefix() + "merged_knowledge_base.md": "# Draft\n\n草稿"})
    monkeypatch.setattr(build_lifecycle, "get_content_store", lambda: store)
    monkeypatch.setattr(build_lifecycle, "resolve_course_storage_scope", lambda *args, **kwargs: scope)
    monkeypatch.setattr(build_lifecycle, "run_store_sync", lambda func, *args, default=None, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(build_lifecycle, "_resolve_current_published_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(build_lifecycle, "read_knowledge_build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(build_lifecycle, "_load_current_published_markdown", lambda *args, **kwargs: ("# Published\n\n正文", now))
    monkeypatch.setattr(build_lifecycle, "load_current_interactive_overlays", lambda *args, **kwargs: [])
    monkeypatch.setattr(build_lifecycle, "apply_interactive_overlays_to_markdown", lambda markdown, *, overlays: markdown)
    monkeypatch.setattr(
        build_lifecycle,
        "_resolve_runtime_build_status",
        lambda *args, **kwargs: KnowledgeBuildStatusResponse(
            status="running",
            requested_at=now,
            stage="drafting",
            draft_available=False,
            planner_session_id="planner-1",
            confirmed_plan_id="plan-1",
            digest_mode="sprint",
        ),
    )
    monkeypatch.setattr(build_lifecycle, "_build_runtime_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        build_lifecycle,
        "get_course_vector_status_by_id",
        lambda *args, **kwargs: CourseVectorStatusResponse(mode="disabled", notice="vector off"),
    )

    response = build_lifecycle.get_docgen_result(session, course_id=COURSE_ID, course_scope=scope)

    assert response.exists is True
    assert response.markdown.startswith("# Published")
    assert response.draft_markdown.startswith("# Draft")
    assert response.source_file_ids == ["file-ready"]
    assert response.prompt == "published prompt"
    assert response.build is not None
    assert response.build.draft_available is True
    assert response.vector_status.mode == "disabled"
    assert response.planner_session_id == "planner-1"
    assert response.confirmed_plan_id == "plan-1"
    assert response.digest_mode == "sprint"
