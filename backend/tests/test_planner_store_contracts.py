from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.models import ChatMessage, ChatSession, Course, CourseFileLink, IngestStatus, RawFile, TaskStatus
from app.schemas.knowledge import BuildPlannerCreateRequest
from app.shared.infra.exceptions import (
    BuildPlannerEmptyPlanError,
    BuildPlannerSessionBusyError,
    BuildPlannerSessionNotFoundError,
    ConfirmedBuildPlanNotFoundError,
    RawFileNotFoundError,
)
from app.shared.infra.workflow.result import ok_result
from app.utils.time import utcnow
from app.repositories.chats_repo import list_sessions_by_course, list_sessions_by_user
from app.workflows.digest.common.models import CourseProfile, DigestMaterialContext, FastTopicHints
from app.workflows.digest.planner import graph as planner_graph
from app.workflows.digest.planner.lib import store as planner_store


COURSE_ID = "course_planner000001"
USER_ID = "user-planner"


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


@pytest.fixture
def managed_planner_session(monkeypatch: pytest.MonkeyPatch, session: Session) -> Session:
    @contextmanager
    def _managed_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(planner_store, "managed_session", _managed_session)
    return session


def _seed_course_and_files(session: Session) -> None:
    session.add(
        Course(
            id=COURSE_ID,
            user_id=USER_ID,
            name="Untitled Course",
            description="",
            user_intent="",
        )
    )
    files = [
        RawFile(
            id="file-ready",
            user_id=USER_ID,
            filename="linear-algebra.md",
            filetype="md",
            file_path="linear-algebra.md",
            status=TaskStatus.COMPLETED.value,
            ingest_status=IngestStatus.READY_FOR_DIGEST.value,
            markdown_content="# 矩阵\n矩阵乘法和秩。",
        ),
        RawFile(
            id="file-pending",
            user_id=USER_ID,
            filename="practice.pdf",
            filetype="pdf",
            file_path="practice.pdf",
            status=TaskStatus.PROCESSING.value,
            ingest_status=IngestStatus.PENDING.value,
            markdown_content="",
        ),
    ]
    session.add_all(files)
    session.add_all(
        [
            CourseFileLink(user_id=USER_ID, course_id=COURSE_ID, file_id=item.id)
            for item in files
        ]
    )
    session.commit()


def test_chat_session_lists_expose_only_latest_course_build_planner_session(session: Session) -> None:
    _seed_course_and_files(session)
    base = datetime(2026, 1, 1, 8, 0, 0)
    session.add_all(
        [
            ChatSession(
                id="planner-old",
                course_id=COURSE_ID,
                user_id=USER_ID,
                title="旧构建方案",
                source="build_planner",
                created_at=base,
                updated_at=base,
                last_message_at=base,
            ),
            ChatSession(
                id="planner-latest",
                course_id=COURSE_ID,
                user_id=USER_ID,
                title="当前构建方案",
                source="build_planner",
                created_at=datetime(2026, 1, 1, 9, 0, 0),
                updated_at=datetime(2026, 1, 1, 9, 0, 0),
                last_message_at=datetime(2026, 1, 1, 9, 0, 0),
            ),
            ChatSession(
                id="course-chat",
                course_id=COURSE_ID,
                user_id=USER_ID,
                title="普通课程对话",
                source="course_chat",
                created_at=datetime(2026, 1, 1, 10, 0, 0),
                updated_at=datetime(2026, 1, 1, 10, 0, 0),
                last_message_at=datetime(2026, 1, 1, 10, 0, 0),
            ),
        ]
    )
    session.commit()

    course_items, course_total = list_sessions_by_course(
        session,
        COURSE_ID,
        user_id=USER_ID,
        limit=10,
        offset=0,
    )
    recent_items, recent_total = list_sessions_by_user(session, user_id=USER_ID, limit=10, offset=0)

    assert course_total == 2
    assert [item.id for item in course_items] == ["course-chat", "planner-latest"]
    assert "planner-old" not in {item.id for item in recent_items}
    assert recent_total == 2


def _material_context() -> DigestMaterialContext:
    return DigestMaterialContext(
        material_hints=FastTopicHints(
            chapter_candidates=["矩阵对象", "线性映射", "习题复盘"],
            high_freq_terms=[("矩阵", 5), ("秩", 3)],
        ),
        learning_domain_profile=CourseProfile(
            course_id=COURSE_ID,
            course_description="线性代数入门材料，强调矩阵运算和空间直觉。",
            discipline="数学",
            sub_discipline="线性代数",
            key_topics=["矩阵", "线性映射", "秩"],
            has_heavy_formulas=True,
        ),
    )


def _plan(*, plan_text: str = "围绕矩阵和线性映射生成一份可执行学习计划。") -> dict[str, Any]:
    return {
        "course_name": "线性代数",
        "course_icon": "calculator",
        "user_prompt": "帮我把线性代数整理成可学习的知识文档",
        "digest_mode": "sprint",
        "planning_note": "用两章快速建立矩阵和线性映射主线",
        "suggestion": "如果想更偏考试，可以增加题型和易错点密度。",
        "plan": plan_text,
        "diagnose": [
            {
                "question": "矩阵乘法和秩的直觉里，你现在更卡哪一个？",
                "purpose": "区分计算规则与空间直觉薄弱点。",
                "options": ["矩阵乘法", "秩的直觉", "都还不熟", "先看例题"],
            }
        ],
        "chapters": [
            {
                "chapter_index": 1,
                "title": "矩阵对象",
                "objective": "识别矩阵、向量和线性变换之间的关系。",
                "required_elements": ["矩阵定义", "矩阵乘法", "秩的直觉"],
                "writing_instructions": "先给判断抓手，再展开常见计算任务。",
            },
            {
                "chapter_index": 2,
                "title": "线性映射",
                "objective": "把矩阵运算连接到空间映射。",
                "required_elements": ["映射视角", "基变换", "例题"],
                "writing_instructions": "用例子说明抽象概念。",
            },
        ],
        "build_constraints": {
            "min_chapters": 2,
            "max_chapters": 2,
            "target_chapter_count": 2,
        },
        "model_override": "primary",
    }


def test_planner_snapshot_helpers_keep_history_and_runtime_contracts() -> None:
    now = utcnow()
    meta = planner_store._planner_session_meta(
        session_id="planner-helpers",
        status="draft",
        user_prompt="学习矩阵",
        digest_mode="systematic",
        selected_file_ids=[" file-a ", "file-a", "", "file-b"],
        model_override="primary",
        latest_plan=_plan(),
        latest_summary="已有大纲",
        confirmed_plan_id="plan-1",
    )
    record = ChatSession(
        id="planner-helpers",
        course_id=COURSE_ID,
        user_id=USER_ID,
        title="规划会话",
        source=planner_store.PLANNER_CHAT_SOURCE,
        meta_json=meta,
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    turns = [
        ChatMessage(
            id=1,
            course_id=COURSE_ID,
            user_id=USER_ID,
            session_id=record.id,
            turn_id="t1",
            source=planner_store.PLANNER_CHAT_SOURCE,
            role="user",
            content="第一轮目标",
            created_at=now,
        ),
        ChatMessage(
            id=2,
            course_id=COURSE_ID,
            user_id=USER_ID,
            session_id=record.id,
            turn_id="t2",
            source=planner_store.PLANNER_CHAT_SOURCE,
            role="assistant",
            content="第一版大纲",
            meta_json={"plan_json": _plan(plan_text="第一版")},
            created_at=now,
        ),
        ChatMessage(
            id=3,
            course_id=COURSE_ID,
            user_id=USER_ID,
            session_id=record.id,
            turn_id="t3",
            source=planner_store.PLANNER_CHAT_SOURCE,
            role="user",
            content="再加强练习",
            created_at=now,
        ),
    ]

    snapshot = planner_store._record_snapshot(record)
    context = planner_store._build_planner_context_payload(record, turns=turns, plan=_plan())
    response = planner_store.planner_session_response_from_state(
        {
            "planner_record": snapshot,
            "planner_turns": [planner_store._turn_snapshot(turn) for turn in turns],
            "plan": _plan(),
            "selected_file_ids": ["file-a", "file-b"],
            "model_override": "primary",
            "workflow_elapsed_ms": 150,
            "prepare_ms": 12,
            "compose_ms": 25,
        }
    )

    assert snapshot["selected_file_ids"] == ["file-a", "file-b"]
    assert snapshot["model_override"] == "primary"
    assert context["planner_turn_count"] == 3
    assert context["user_revision_count"] == 1
    assert context["assistant_revision_count"] == 1
    assert context["planner_outline_markdown"] == "第一版大纲"
    assert "再加强练习" in context["docgen_history_brief"]
    assert response.latest_plan.selected_file_ids == ["file-a", "file-b"]
    assert not hasattr(response, "runtime_stats")


def test_prepare_save_confirm_and_status_round_trip(managed_planner_session: Session) -> None:
    _seed_course_and_files(managed_planner_session)

    created = planner_store.prepare_planner_run(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-round-trip",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "requested_file_ids": ["file-ready", "file-pending"],
            "user_prompt": "帮我把线性代数整理成可学习的知识文档",
            "digest_mode": "sprint",
            "model_override": "primary",
        }
    )

    assert created["file_ids"] == ["file-ready"]
    assert created["selected_file_ids"] == ["file-ready", "file-pending"]
    assert created["planner_context_stats"]["stored_turn_count"] == 1
    assert created["planner_record"]["status"] == "planning"

    saved = planner_store.save_planner_result(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-round-trip",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "generated_course_name": "线性代数速成",
            "generated_course_icon_key": "math",
            "planning_note": "用两章快速建立矩阵和线性映射主线",
            "model_override": "primary",
        },
        plan=_plan(),
        material_context=_material_context(),
    )

    course = managed_planner_session.get(Course, COURSE_ID)
    assert course is not None
    assert course.name == "线性代数速成"
    assert "线性代数入门材料" in course.description
    assert course.user_intent == "用两章快速建立矩阵和线性映射主线"
    assert saved["planner_record"]["status"] == "draft"
    assert saved["model_override"] == "primary"
    assert managed_planner_session.exec(select(ChatMessage)).all()[-1].role == "assistant"

    appended = planner_store.prepare_planner_run(
        {
            "planner_operation": "append",
            "planner_session_id": "planner-round-trip",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "feedback_message": "再补一个习题复盘章节",
            "model_override": "primary",
        }
    )

    assert appended["latest_plan"]["plan"] == _plan()["plan"]
    assert appended["planner_context_stats"]["stored_turn_count"] == 3
    assert any("再补一个习题复盘章节" in item for item in appended["message_history"])

    revised_plan = _plan(plan_text="加入习题复盘后的三段式学习计划。")
    revised_plan["chapters"].append(
        {
            "chapter_index": 3,
            "title": "习题复盘",
            "objective": "把常见题型和错误边界沉淀下来。",
            "required_elements": ["常见题型", "错误边界", "复盘清单"],
            "writing_instructions": "以任务清单组织练习和复盘。",
        }
    )
    planner_store.save_planner_result(
        {
            "planner_operation": "append",
            "planner_session_id": "planner-round-trip",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "generated_course_name": "",
            "model_override": "primary",
        },
        plan=revised_plan,
        material_context=_material_context(),
    )

    confirmed = planner_store.confirm_planner_session(
        managed_planner_session,
        course=course,
        user_id=USER_ID,
        session_id="planner-round-trip",
    )
    repeated = planner_store.confirm_planner_session(
        managed_planner_session,
        course=course,
        user_id=USER_ID,
        session_id="planner-round-trip",
    )
    latest = planner_store.get_latest_planner_session(
        managed_planner_session,
        course=course,
        user_id=USER_ID,
    )
    click_context = planner_store.get_planner_adjust_click_context(
        managed_planner_session,
        course=course,
        user_id=USER_ID,
        session_id="planner-round-trip",
    )

    assert confirmed.version_no == 1
    assert repeated.confirmed_plan_id == confirmed.confirmed_plan_id
    assert repeated.version_no == 1
    assert confirmed.selected_file_ids == ["file-ready", "file-pending"]
    assert confirmed.model_override == "primary"
    assert confirmed.diagnose[0].question.startswith("矩阵乘法")
    assert latest is not None
    assert latest.status == "confirmed"
    assert latest.revision == 4
    assert click_context["has_latest_plan"] is True
    assert click_context["latest_plan_chapter_count"] == 3

    stored_plan = planner_store.get_confirmed_plan_or_raise(
        managed_planner_session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        plan_id=confirmed.confirmed_plan_id,
    )
    assert stored_plan.plan == "加入习题复盘后的三段式学习计划。"
    assert stored_plan.plan_json["planner_context"]["assistant_revision_count"] == 2
    assert "再补一个习题复盘章节" in stored_plan.plan_json["docgen_history_brief"]
    assert stored_plan.plan_json["diagnose"][0]["options"] == ["矩阵乘法", "秩的直觉", "都还不熟", "先看例题"]
    assert stored_plan.plan_json["chapters"][2]["title"] == "习题复盘"

    planner_store.mark_confirmed_plan_status(
        managed_planner_session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        plan_id=confirmed.confirmed_plan_id,
        status="building",
    )
    assert planner_store.get_planner_adjust_click_context(
        managed_planner_session,
        course=course,
        user_id=USER_ID,
        session_id="planner-round-trip",
    )["status"] == "building"

    planner_store.mark_planner_session_failed(course_id=COURSE_ID, user_id=USER_ID, session_id="planner-round-trip")
    assert managed_planner_session.get(ChatSession, "planner-round-trip").meta_json["planner_status"] == "failed"
    planner_store.mark_planner_session_cancelled(course_id=COURSE_ID, user_id=USER_ID, session_id="planner-round-trip")
    assert managed_planner_session.get(ChatSession, "planner-round-trip").meta_json["planner_status"] == "cancelled"
    planner_store.mark_planner_session_draft(course_id=COURSE_ID, user_id=USER_ID, session_id="planner-round-trip")
    assert managed_planner_session.get(ChatSession, "planner-round-trip").meta_json["planner_status"] == "draft"


def test_save_planner_result_persists_diagnosis_draft_before_plan(managed_planner_session: Session) -> None:
    _seed_course_and_files(managed_planner_session)
    planner_store.prepare_planner_run(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-diagnose-first",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "requested_file_ids": ["file-ready"],
            "user_prompt": "帮我把线性代数整理成可学习的知识文档",
            "digest_mode": "sprint",
            "model_override": "primary",
        }
    )
    result = planner_store.save_planner_result(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-diagnose-first",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "generated_course_name": "线性代数速成",
            "generated_course_icon_key": "math",
            "planning_note": "用两章快速建立矩阵和线性映射主线",
            "model_override": "primary",
        },
        plan={
            "planner_stage": "diagnosis",
            "course_name": "线性代数",
            "user_prompt": "帮我把线性代数整理成可学习的知识文档",
            "digest_mode": "sprint",
            "planning_note": "用两章快速建立矩阵和线性映射主线",
            "diagnose": [
                {
                    "question": "矩阵和线性映射里你更想先补哪块？",
                    "purpose": "决定正式方案的章节优先级和例题密度。",
                    "options": ["矩阵乘法", "线性映射", "秩的直觉", "例题带路"],
                }
            ],
            "diagnose_status": "pending",
        },
        material_context=_material_context(),
    )
    response = planner_store.planner_session_response_from_state(result)

    assert response.latest_plan.diagnose_status == "pending"
    assert response.latest_plan.plan == ""
    assert response.latest_plan.chapters == []
    assert response.latest_plan.diagnose[0].options == ["矩阵乘法", "线性映射", "秩的直觉", "例题带路"]
    assert response.turns[-1].role == "assistant"
    assert response.turns[-1].plan_json is not None
    assert response.turns[-1].plan_json["diagnose_status"] == "pending"
    assert result["planner_turns"][-1]["plan_json"]["planner_stage"] == "diagnosis"


def test_create_operation_reuses_course_planner_session(managed_planner_session: Session) -> None:
    _seed_course_and_files(managed_planner_session)
    planner_store.prepare_planner_run(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-singleton",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "requested_file_ids": ["file-ready"],
            "user_prompt": "先生成一版线性代数方案",
            "digest_mode": "sprint",
        }
    )
    planner_store.save_planner_result(
        {
            "planner_operation": "create",
            "planner_session_id": "planner-singleton",
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "generated_course_name": "线性代数速成",
        },
        plan=_plan(),
        material_context=_material_context(),
    )
    course = managed_planner_session.get(Course, COURSE_ID)
    assert course is not None

    reusable_id = planner_store.get_reusable_planner_session_id(course=course, user_id=USER_ID)
    assert reusable_id == "planner-singleton"

    restarted = planner_store.prepare_planner_run(
        {
            "planner_operation": "create",
            "planner_session_id": reusable_id,
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "requested_file_ids": ["file-ready", "file-pending"],
            "user_prompt": "重新按考试冲刺生成方案",
            "digest_mode": "sprint",
        }
    )
    records = managed_planner_session.exec(
        select(ChatSession).where(
            ChatSession.course_id == COURSE_ID,
            ChatSession.user_id == USER_ID,
            ChatSession.source == planner_store.PLANNER_CHAT_SOURCE,
        )
    ).all()
    turns = managed_planner_session.exec(
        select(ChatMessage).where(
            ChatMessage.session_id == "planner-singleton",
            ChatMessage.source == planner_store.PLANNER_CHAT_SOURCE,
        )
    ).all()

    assert len(records) == 1
    assert restarted["planner_record"]["id"] == "planner-singleton"
    assert restarted["planner_record"]["status"] == "planning"
    assert restarted["selected_file_ids"] == ["file-ready", "file-pending"]
    assert records[0].meta_json["latest_plan"]["plan"] == _plan()["plan"]
    assert [turn.role for turn in turns] == ["user", "assistant", "user"]


def test_create_planner_entry_uses_reusable_course_session(monkeypatch: pytest.MonkeyPatch) -> None:
    course = Course(id=COURSE_ID, user_id=USER_ID, name="线性代数", description="", user_intent="")
    captured: dict[str, Any] = {}
    now = utcnow()

    def fake_get_reusable_planner_session_id(*, course: Course, user_id: str) -> str:
        captured["reusable_lookup"] = {"course_id": course.id, "user_id": user_id}
        return "planner-existing"

    async def fake_run_build_planner_workflow(**kwargs: Any):
        captured["workflow_kwargs"] = dict(kwargs)
        return ok_result(
            {
                "course_id": course.id,
                "planner_session_id": kwargs["planner_session_id"],
                "selected_file_ids": [],
                "model_override": kwargs.get("model"),
                "plan": _plan(),
                "planner_turns": [],
                "planner_record": {
                    "id": kwargs["planner_session_id"],
                    "course_id": course.id,
                    "title": "已有构建方案",
                    "status": "draft",
                    "created_at": now,
                    "updated_at": now,
                    "confirmed_plan_id": None,
                    "model_override": kwargs.get("model"),
                },
            }
        )

    monkeypatch.setattr(planner_graph, "get_reusable_planner_session_id", fake_get_reusable_planner_session_id)
    monkeypatch.setattr(planner_graph, "run_build_planner_workflow", fake_run_build_planner_workflow)
    monkeypatch.setattr(planner_graph, "_log_planner_runtime", lambda **_: None)

    response = asyncio.run(
        planner_graph.create_build_planner_session(
            course=course,
            user_id=USER_ID,
            payload=BuildPlannerCreateRequest(user_prompt="请重新规划线性代数课程"),
        )
    )

    assert captured["reusable_lookup"] == {"course_id": COURSE_ID, "user_id": USER_ID}
    assert captured["workflow_kwargs"]["planner_session_id"] == "planner-existing"
    assert captured["workflow_kwargs"]["planner_operation"] == "create"
    assert response.session_id == "planner-existing"


def test_planner_store_rejects_invalid_files_busy_sessions_and_empty_confirm(
    managed_planner_session: Session,
) -> None:
    _seed_course_and_files(managed_planner_session)

    with pytest.raises(RawFileNotFoundError):
        planner_store.prepare_planner_run(
            {
                "planner_operation": "create",
                "planner_session_id": "planner-missing-file",
                "course_id": COURSE_ID,
                "user_id": USER_ID,
                "requested_file_ids": ["file-missing"],
                "user_prompt": "学习线代",
            }
        )

    managed_planner_session.add(
        ChatSession(
            id="planner-busy",
            course_id=COURSE_ID,
            user_id=USER_ID,
            title="Busy",
            source=planner_store.PLANNER_CHAT_SOURCE,
            meta_json=planner_store._planner_session_meta(
                session_id="planner-busy",
                status="planning",
                user_prompt="学习线代",
                digest_mode="systematic",
                selected_file_ids=[],
            ),
        )
    )
    managed_planner_session.add(
        ChatSession(
            id="planner-empty",
            course_id=COURSE_ID,
            user_id=USER_ID,
            title="Empty",
            source=planner_store.PLANNER_CHAT_SOURCE,
            meta_json=planner_store._planner_session_meta(
                session_id="planner-empty",
                status="draft",
                user_prompt="学习线代",
                digest_mode="systematic",
                selected_file_ids=[],
            ),
        )
    )
    managed_planner_session.commit()
    course = managed_planner_session.get(Course, COURSE_ID)
    assert course is not None

    with pytest.raises(BuildPlannerSessionBusyError):
        planner_store.prepare_planner_run(
            {
                "planner_operation": "create",
                "planner_session_id": "planner-blocked",
                "course_id": COURSE_ID,
                "user_id": USER_ID,
                "user_prompt": "学习线代",
            }
        )

    with pytest.raises(BuildPlannerEmptyPlanError):
        planner_store.confirm_planner_session(
            managed_planner_session,
            course=course,
            user_id=USER_ID,
            session_id="planner-empty",
        )

    with pytest.raises(BuildPlannerSessionNotFoundError):
        planner_store.get_planner_adjust_click_context(
            managed_planner_session,
            course=course,
            user_id=USER_ID,
            session_id="planner-not-found",
        )

    with pytest.raises(ConfirmedBuildPlanNotFoundError):
        planner_store.get_confirmed_plan_or_raise(
            managed_planner_session,
            course_id=COURSE_ID,
            user_id=USER_ID,
            plan_id="plan-missing",
        )
