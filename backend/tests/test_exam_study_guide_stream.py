from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import Response
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - register all SQLModel tables
from app.api import exams as exams_api
from app.api.deps import CurrentUserContext
from app.models import (
    Course,
    ExamPaper,
    ExamPaperItem,
    ExamStudyGuideCache,
    QuestionKnowledgeUnitLink,
    UserKnowledgeState,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import exams_repo
from app.schemas.exams import ExamStudyGuideResponse
from app.utils.time import utcnow


COURSE_ID = "course_studyguide00"
USER_ID = "study-guide-user"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        @contextmanager
        def managed_session() -> Iterator[Session]:
            yield db

        monkeypatch.setattr(exams_api, "managed_session", managed_session)
        yield db


def seed_graded_paper(session: Session) -> ExamPaper:
    session.add(
        Course(
            id=COURSE_ID,
            user_id=USER_ID,
            name="线性代数",
            description="矩阵与线性映射",
            user_intent="复习薄弱知识点",
        )
    )
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="graded",
        total_items=0,
        score_obtained=0,
        total_score=0,
        graded_at=utcnow(),
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def build_guide(paper_id: int) -> ExamStudyGuideResponse:
    return ExamStudyGuideResponse(
        exam_paper_id=paper_id,
        course_name="线性代数",
        generated_at=utcnow(),
        overall_summary="本次作答已完成，建议继续巩固矩阵秩与线性映射的核心概念。",
        strengths=["基础概念掌握稳定"],
        priority_gaps=["矩阵秩"],
        action_steps=["回顾定义并完成变式练习"],
        review_tasks=[],
        focus_units=[],
    )


def test_active_study_guide_generation_expires_after_stale_window() -> None:
    now = utcnow()
    active = ExamStudyGuideCache(
        exam_paper_id=1,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="generating",
        updated_at=now,
    )
    stale = ExamStudyGuideCache(
        exam_paper_id=2,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="generating",
        updated_at=now - timedelta(minutes=11),
    )

    assert exams_api._is_active_study_guide_generation(active, as_of=now) is True
    assert exams_api._is_active_study_guide_generation(stale, as_of=now) is False


@pytest.mark.anyio
async def test_stale_generation_is_reclaimed_with_a_unique_task_key(
    session: Session,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    old_token = "old-generation-token"
    session.add(
        ExamStudyGuideCache(
            exam_paper_id=paper_id,
            course_id=COURSE_ID,
            user_id=USER_ID,
            status="generating",
            guide_json=exams_api._study_guide_generation_cache_json(old_token),
            updated_at=utcnow() - timedelta(minutes=11),
        )
    )
    session.commit()

    class Registry:
        def __init__(self) -> None:
            self.cancelled: list[dict[str, object]] = []
            self.spawned: list[dict[str, object]] = []

        async def cancel_matching(self, **kwargs) -> int:
            self.cancelled.append(kwargs)
            return 1

        def spawn(self, coro, **kwargs):
            self.spawned.append(kwargs)
            coro.close()
            return None

    registry = Registry()
    scheduled = await exams_api._schedule_exam_study_guide_task(
        registry,
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )

    assert scheduled is True
    assert len(registry.cancelled) == 1
    assert len(registry.spawned) == 1
    session.expire_all()
    claimed = exams_repo.get_study_guide_cache(session, exam_paper_id=paper_id)
    assert claimed is not None
    new_token = exams_api._study_guide_cache_generation_token(claimed)
    assert new_token and new_token != old_token
    assert registry.spawned[0]["dedupe_key"].endswith(new_token)


def test_stale_worker_cannot_publish_after_generation_ownership_changes(
    session: Session,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    active_token = "new-owner-token"
    exams_repo.upsert_study_guide_cache(
        session,
        exam_paper_id=paper_id,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="generating",
        guide_json=exams_api._study_guide_generation_cache_json(active_token),
    )
    guide = build_guide(paper_id)

    assert exams_repo.update_owned_study_guide_cache(
        session,
        exam_paper_id=paper_id,
        generation_token="stale-owner-token",
        status="completed",
        guide_json=guide.model_dump_json(),
        generated_at=guide.generated_at,
    ) is False
    assert exams_repo.update_owned_study_guide_cache(
        session,
        exam_paper_id=paper_id,
        generation_token=active_token,
        status="completed",
        guide_json=guide.model_dump_json(),
        generated_at=guide.generated_at,
    ) is True


@pytest.mark.anyio
async def test_regular_get_waits_for_active_shared_generation_without_rescheduling(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    exams_repo.upsert_study_guide_cache(
        session,
        exam_paper_id=paper_id,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="generating",
        guide_json=exams_api._study_guide_generation_cache_json("active-owner-token"),
    )
    guide = build_guide(paper_id)

    async def fail_if_rescheduled(*_args, **_kwargs):
        raise AssertionError("an active shared generation must not be scheduled twice")

    async def return_shared_result(**_kwargs):
        assert session.in_transaction() is False
        return guide

    monkeypatch.setattr(exams_api, "_schedule_exam_study_guide_task", fail_if_rescheduled)
    monkeypatch.setattr(exams_api, "_wait_for_exam_study_guide_result", return_shared_result)

    response = await exams_api.exam_study_guide(
        request=SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(background_task_registry=object()))
        ),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data == guide


@pytest.mark.anyio
async def test_regular_get_releases_request_transaction_before_scheduling(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    guide = build_guide(paper_id)

    async def assert_released_before_schedule(*_args, **_kwargs):
        assert session.in_transaction() is False
        return True

    async def return_shared_result(**_kwargs):
        assert session.in_transaction() is False
        return guide

    monkeypatch.setattr(
        exams_api,
        "_schedule_exam_study_guide_task",
        assert_released_before_schedule,
    )
    monkeypatch.setattr(exams_api, "_wait_for_exam_study_guide_result", return_shared_result)

    response = await exams_api.exam_study_guide(
        request=SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(background_task_registry=object()))
        ),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data == guide


@pytest.mark.anyio
async def test_study_guide_background_publishes_progress_and_completed_payload(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_workflow(**kwargs) -> ExamStudyGuideResponse:
        kwargs["progress_callback"](
            {
                "stage": "study_guide",
                "step": "generate_study_guide",
                "detail": "正在生成学习指南...",
            }
        )
        guide = build_guide(paper_id)
        kwargs["content_callback"](guide)
        return guide

    monkeypatch.setattr(exams_api, "run_exam_study_guide_workflow", fake_workflow)
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_study_guide_event",
        lambda _course_id, _paper_id, event, data: events.append((event, data)),
    )

    await exams_api._run_exam_study_guide_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )

    cache = exams_repo.get_study_guide_cache(session, exam_paper_id=paper_id)
    assert cache is not None
    assert cache.status == "completed"
    assert [event for event, _payload in events] == ["progress", "progress", "content", "done"]
    content_payload = next(payload for event, payload in events if event == "content")
    assert content_payload["sequence"] == 1
    assert content_payload["draft"]["exam_paper_id"] == paper_id
    assert events[-1][1]["status"] == "completed"
    assert events[-1][1]["guide"]["exam_paper_id"] == paper_id


@pytest.mark.anyio
async def test_study_guide_background_cancellation_releases_generating_cache(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    generation_started = asyncio.Event()
    never_finish = asyncio.Event()

    async def cancelled_workflow(**_kwargs) -> ExamStudyGuideResponse:
        generation_started.set()
        await never_finish.wait()
        raise AssertionError("cancelled workflow unexpectedly resumed")

    monkeypatch.setattr(exams_api, "run_exam_study_guide_workflow", cancelled_workflow)
    task = asyncio.create_task(
        exams_api._run_exam_study_guide_background(
            course_id=COURSE_ID,
            user_id=USER_ID,
            paper_id=paper_id,
        )
    )
    await generation_started.wait()

    generating = exams_repo.get_study_guide_cache(session, exam_paper_id=paper_id)
    assert generating is not None
    assert generating.status == "generating"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    session.expire_all()
    cancelled = exams_repo.get_study_guide_cache(session, exam_paper_id=paper_id)
    assert cancelled is not None
    assert cancelled.status == "failed"
    assert cancelled.error_message == "study_guide_generation_cancelled"
    assert exams_api._is_active_study_guide_generation(cancelled) is False


@pytest.mark.anyio
async def test_study_guide_stream_returns_cached_guide_as_terminal_sse(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    guide = build_guide(paper_id)
    exams_repo.upsert_study_guide_cache(
        session,
        exam_paper_id=paper_id,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="completed",
        guide_json=guide.model_dump_json(),
        generated_at=guide.generated_at,
    )
    monkeypatch.setattr(
        exams_api,
        "get_current_user_context",
        lambda _request, _response, _session: CurrentUserContext(
            user_id=USER_ID,
            email=None,
            is_local=True,
        ),
    )

    async def is_disconnected() -> bool:
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None)),
        is_disconnected=is_disconnected,
    )
    stream = await exams_api.exam_study_guide_stream(
        request=request,
        response=Response(),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
    )

    chunks: list[str] = []
    async for chunk in stream.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    body = "".join(chunks)
    data_line = next(line for line in body.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))

    assert stream.media_type == "text/event-stream"
    assert "event: done" in body
    assert payload["status"] == "completed"
    assert payload["guide"]["exam_paper_id"] == paper_id


def test_generating_cache_restores_latest_study_guide_draft() -> None:
    guide = build_guide(42)
    cache = ExamStudyGuideCache(
        exam_paper_id=42,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="generating",
        guide_json=exams_api._study_guide_draft_cache_json(guide, sequence=7),
    )

    restored = exams_api._cached_study_guide_draft(cache)

    assert restored is not None
    sequence, draft = restored
    assert sequence == 7
    assert draft == guide


def test_legacy_study_guide_cache_with_internal_review_tasks_is_regenerated() -> None:
    guide = build_guide(42).model_copy(
        update={
            "review_tasks": ["完成专项练习"],
            "action_steps": ["步骤一", "步骤二", "步骤三", "步骤四"],
        }
    )
    cache = ExamStudyGuideCache(
        exam_paper_id=42,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="completed",
        guide_json=guide.model_dump_json(),
    )

    assert exams_api._cached_study_guide_response(cache) is None


def test_legacy_study_guide_cache_without_paper_metric_schema_is_regenerated() -> None:
    payload = build_guide(42).model_dump(mode="json")
    payload.pop("schema_version")
    cache = ExamStudyGuideCache(
        exam_paper_id=42,
        course_id=COURSE_ID,
        user_id=USER_ID,
        status="completed",
        guide_json=json.dumps(payload, ensure_ascii=False),
    )

    assert exams_api._cached_study_guide_response(cache) is None


def test_study_guide_unit_evidence_uses_current_paper_scores_and_coverage_weights() -> None:
    items = [
        ExamPaperItem(
            id=1,
            exam_paper_id=42,
            question_template_id=101,
            item_order=1,
            stem_snapshot="第一题",
            answer_snapshot="A",
            explanation_snapshot="解析",
            difficulty="medium",
            question_type="single_choice",
            score=4.0,
            score_obtained=2.0,
            score_max=4.0,
            is_correct=False,
        ),
        ExamPaperItem(
            id=2,
            exam_paper_id=42,
            question_template_id=102,
            item_order=2,
            stem_snapshot="第二题",
            answer_snapshot="B",
            explanation_snapshot="解析",
            difficulty="medium",
            question_type="single_choice",
            score=2.0,
            score_obtained=2.0,
            score_max=2.0,
            is_correct=True,
        ),
    ]
    evidence = exams_api._study_guide_unit_evidence(
        items,
        {
            1: [{"knowledge_unit_id": 11, "coverage_weight": 1.0}],
            2: [
                {"knowledge_unit_id": 11, "coverage_weight": 0.5},
                {"knowledge_unit_id": 12, "coverage_weight": 0.5},
            ],
        },
    )

    assert evidence[11]["paper_attempts"] == 2
    assert evidence[11]["paper_correct_attempts"] == 1
    assert evidence[11]["paper_score_obtained"] == pytest.approx(3.0)
    assert evidence[11]["paper_score_max"] == pytest.approx(5.0)
    assert evidence[12]["paper_attempts"] == 1
    assert evidence[12]["paper_score_obtained"] == pytest.approx(1.0)
    assert evidence[12]["paper_score_max"] == pytest.approx(1.0)


def test_unit_performance_includes_high_mastery_and_unprofiled_paper_units() -> None:
    units = {
        11: KnowledgeUnit(
            id=11,
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name="反比例函数",
            normalized_name="反比例函数",
        ),
        12: KnowledgeUnit(
            id=12,
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name="一次函数",
            normalized_name="一次函数",
        ),
    }
    high_mastery_state = UserKnowledgeState(
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=11,
        mastery_score=0.95,
        total_attempts=20,
        correct_attempts=18,
    )

    performance = exams_api._study_guide_unit_performance_payload(
        {
            11: {
                "paper_attempts": 2,
                "paper_correct_attempts": 1,
                "paper_score_obtained": 3.0,
                "paper_score_max": 5.0,
            },
            12: {
                "paper_attempts": 1,
                "paper_correct_attempts": 1,
                "paper_score_obtained": 1.0,
                "paper_score_max": 1.0,
            },
        },
        knowledge_unit_by_id=units,
        knowledge_state_by_id={11: high_mastery_state},
    )

    assert [point["knowledge_unit_id"] for point in performance] == [11, 12]
    assert performance[0]["paper_score_rate"] == pytest.approx(0.6)
    assert performance[0]["cumulative_mastery_score"] == pytest.approx(0.95)
    assert "累计画像：掌握度 95%" in str(performance[0]["profile_context"])
    assert performance[1]["cumulative_mastery_score"] is None
    assert performance[1]["profile_context"] == "累计画像：暂无可靠历史记录。"


@pytest.mark.anyio
async def test_study_guide_detail_forwards_paper_metrics_and_cumulative_profile_context(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = seed_graded_paper(session)
    unit = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="矩阵乘法",
        normalized_name="矩阵乘法",
    )
    session.add(unit)
    session.commit()
    session.refresh(unit)

    item = ExamPaperItem(
        exam_paper_id=int(paper.id or 0),
        question_template_id=101,
        item_order=1,
        stem_snapshot="计算矩阵乘积",
        answer_snapshot="参考答案",
        explanation_snapshot="参考解析",
        difficulty="medium",
        question_type="short_answer",
        score=4.0,
        score_obtained=1.0,
        score_max=4.0,
        is_correct=False,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    session.add_all(
        [
            QuestionKnowledgeUnitLink(
                exam_paper_item_id=int(item.id or 0),
                knowledge_unit_id=int(unit.id or 0),
                coverage_weight=1.0,
            ),
            UserKnowledgeState(
                user_id=USER_ID,
                course_id=COURSE_ID,
                knowledge_unit_id=int(unit.id or 0),
                mastery_score=0.9,
                total_attempts=20,
                correct_attempts=18,
            ),
        ]
    )
    session.commit()

    captured: dict[str, object] = {}

    async def fake_workflow(**kwargs) -> ExamStudyGuideResponse:
        captured.update(kwargs)
        return build_guide(int(paper.id or 0))

    monkeypatch.setattr(exams_api, "run_exam_study_guide_workflow", fake_workflow)

    response = await exams_api._study_guide_detail(session, paper)

    forwarded = captured["knowledge_unit_performance"]
    assert isinstance(forwarded, list)
    assert len(forwarded) == 1
    point = forwarded[0]
    assert point["knowledge_unit_name"] == "矩阵乘法"
    assert point["paper_score_rate"] == pytest.approx(0.25)
    assert point["cumulative_mastery_score"] == pytest.approx(0.9)
    assert "累计画像：掌握度 90%" in point["profile_context"]
    assert response.focus_units[0].paper_score_rate == pytest.approx(0.25)
    assert response.focus_units[0].mastery_score == pytest.approx(0.9)
    assert "累计" not in response.focus_units[0].reason


def test_study_guide_normalization_uses_current_paper_metrics_and_keeps_profile_context() -> None:
    guide = build_guide(42).model_copy(
        update={
            "strengths": ["优势一", "优势二", "优势三"],
            "focus_units": [],
            "priority_gaps": ["缺口一", "缺口二", "缺口三", "缺口四"],
            "action_steps": ["步骤一", "步骤二", "步骤三", "步骤四"],
        }
    )

    normalized = exams_api._normalize_study_guide_response(
        guide,
        unit_performance=[
            {
                "knowledge_unit_id": 12,
                "knowledge_unit_name": "反比例函数",
                "paper_attempts": 2,
                "paper_correct_attempts": 0,
                "paper_score_obtained": 1.0,
                "paper_score_max": 4.0,
                "paper_score_rate": 0.25,
                "cumulative_mastery_score": 0.9,
                "paper_evidence": "本卷关联 2 题，答对 0 题；按关联权重计 1/4 分，得分率 25%。",
                "profile_context": "累计画像：掌握度 90%，累计练习 20 次，答对 18 次。",
            }
        ],
    )

    assert len(normalized.strengths) == 2
    assert len(normalized.priority_gaps) == 3
    assert len(normalized.action_steps) == 3
    assert normalized.review_tasks == []
    assert normalized.focus_units[0].paper_attempts == 2
    assert normalized.focus_units[0].paper_correct_attempts == 0
    assert normalized.focus_units[0].paper_score_rate == 0.25
    assert normalized.focus_units[0].mastery_score == 0.9
    assert normalized.focus_units[0].reason == "本卷关联 2 题，答对 0 题；按关联权重计 1/4 分，得分率 25%。"
    assert "累计" not in normalized.focus_units[0].reason


def test_stream_draft_reveals_authoritative_focus_only_after_focus_section_starts() -> None:
    summary_draft = build_guide(42).model_copy(
        update={
            "strengths": [],
            "focus_units": [],
            "priority_gaps": [],
            "action_steps": [],
        }
    )
    unit_performance = [
        {
            "knowledge_unit_id": 12,
            "knowledge_unit_name": "反比例函数",
            "paper_attempts": 2,
            "paper_correct_attempts": 0,
            "paper_score_obtained": 0.0,
            "paper_score_max": 2.0,
            "paper_score_rate": 0.0,
            "cumulative_mastery_score": 0.9,
            "paper_evidence": "本卷关联 2 题，答对 0 题。",
        }
    ]

    normalized_summary = exams_api._normalize_study_guide_stream_draft(
        summary_draft,
        unit_performance=unit_performance,
    )
    normalized_focus = exams_api._normalize_study_guide_stream_draft(
        summary_draft.model_copy(update={"priority_gaps": ["函数关系辨析不稳"]}),
        unit_performance=unit_performance,
    )

    assert normalized_summary.focus_units == []
    assert [unit.knowledge_unit_name for unit in normalized_focus.focus_units] == ["反比例函数"]


def test_study_guide_review_reason_does_not_leak_internal_enum() -> None:
    assert exams_api._study_guide_public_review_reason("repeated_wrong") == "近期同类题连续出错"
    assert exams_api._study_guide_public_review_reason("unexpected_internal_code") == "建议优先复习"
