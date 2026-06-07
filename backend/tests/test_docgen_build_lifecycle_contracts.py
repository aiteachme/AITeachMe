from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
import app.shared.infra.knowledge.build_store as build_store
from app.models import Course, CourseFileLink, IngestStatus, RawFile, TaskStatus
from app.models.build_planner import ConfirmedBuildPlan
from app.schemas.knowledge import CourseVectorStatusResponse, KnowledgeBuildStatusResponse
from app.shared.infra.exceptions import (
    ConfirmedBuildPlanRequiredError,
    CourseBuildLockConflictError,
    NoReadyFilesForDocGenError,
)
from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import build_lifecycle


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
            "model_override": "qwen-flash",
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
    assert build_data.model_override == "qwen-flash"
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
    monkeypatch.setattr(build_lifecycle, "read_knowledge_manifest", lambda *args, **kwargs: manifest)
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
    assert result.aggregate is not None
    assert result.docgen is not None
    assert result.docgen.status == "running"
    assert result.docgen_metrics is not None
    assert result.graph_metrics.doc_sync_section_count == 3
    assert result.docgen_preview is not None
    assert result.docgen_preview.draft_excerpt.startswith("# Draft")


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
    monkeypatch.setattr(build_lifecycle, "read_knowledge_manifest", lambda *args, **kwargs: manifest)
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
