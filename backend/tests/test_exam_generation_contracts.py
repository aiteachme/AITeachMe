from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import exams as exams_api
from app.api.deps import CurrentUserContext
import app.models  # noqa: F401 - ensure all SQLModel tables are registered
from app.models import Course, ExamPaper, ExamPaperItem, QuestionTemplate
from app.models.knowledge_unit import KnowledgeUnit
from app.schemas.exams import ExamGenerateRequest, ExamSubmitRequest, PaperPreview
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.examine.exam_grade.lib.grader import ExamItemGradeDecision
from app.workflows.examine.question_build import prompts as question_prompts
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.lib.model_policy import (
    QuestionBuildModelStep,
    question_build_completion_kwargs,
)
from app.workflows.examine.question_build.nodes import filter_knowledge_units as filter_units_node
from app.workflows.support.exam_pool_policy import (
    exam_candidate_unit_limit,
    exam_ready_units_per_chapter_floor,
    exam_readiness_candidate_target,
)


COURSE_ID = "course_exam00000000"
USER_ID = "user-exam"


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
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def managed_exam_session(monkeypatch: pytest.MonkeyPatch, session: Session) -> Session:
    @contextmanager
    def _managed_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(exams_api, "managed_session", _managed_session)
    return session


def _seed_exam_course(session: Session, *, with_units: bool = True) -> list[KnowledgeUnit]:
    session.add(
        Course(
            id=COURSE_ID,
            user_id=USER_ID,
            name="Linear Algebra",
            description="Matrix and linear map practice",
            user_intent="Prepare targeted exercises",
        )
    )
    units: list[KnowledgeUnit] = []
    if with_units:
        units = [
            KnowledgeUnit(
                course_id=COURSE_ID,
                knowledge_unit_type="concept",
                canonical_name="Matrices",
                normalized_name="matrices",
                summary="Matrix operations and rank.",
                status="active",
            ),
            KnowledgeUnit(
                course_id=COURSE_ID,
                knowledge_unit_type="concept",
                canonical_name="Linear Maps",
                normalized_name="linear_maps",
                summary="Linear maps and basis changes.",
                status="active",
            ),
        ]
        session.add_all(units)
    session.commit()
    for unit in units:
        session.refresh(unit)
    return units


def _workflow_result(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        failed=False,
        error=None,
        value=payload,
        require_value=lambda: payload,
    )


def test_exam_candidate_pool_policy_matches_default_practice_and_paper_needs() -> None:
    assert exam_candidate_unit_limit(1) == 24
    assert exam_candidate_unit_limit(8) == 32
    assert exam_candidate_unit_limit(24) == 60
    assert exam_readiness_candidate_target(2) == 32
    assert exam_readiness_candidate_target(12) == 48
    assert exam_ready_units_per_chapter_floor(8) == 4


def test_text_exam_prompt_keeps_source_until_context_safety_limit() -> None:
    marker = "SOURCE_MIDDLE_MARKER"
    messages = question_prompts.build_text_exam_messages(
        course_name="测试课程",
        knowledge_text=f"开头\n{marker}\n结尾",
        num_questions=2,
        difficulty="medium",
    )

    payload_text = messages[-1]["content"]
    assert marker in payload_text
    assert '"knowledge_text_truncated": false' in payload_text


def test_text_exam_prompt_marks_only_extreme_source_compression() -> None:
    messages = question_prompts.build_text_exam_messages(
        course_name="测试课程",
        knowledge_text="甲" * 90000,
        num_questions=2,
        difficulty="medium",
    )

    payload_text = messages[-1]["content"]
    assert '"knowledge_text_truncated": true' in payload_text
    assert "学习资料过长，已保留开头和结尾" in payload_text


def test_exam_config_snapshot_normalizes_hash_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = exams_api._build_exam_config_snapshot(
        course_id="course_math00000000",
        user_id="user-1",
        exam_mode="web_practice",
        question_count=3,
        user_prompt="  focus   on weak   units  ",
        sample_file_ids=[" b ", "a", "", "a"],
        knowledge_unit_ids=[2, 1, 2, 0, -1],
        mastery_fingerprint="fingerprint",
    )

    assert snapshot["user_prompt"] == "focus on weak units"
    assert snapshot["sample_file_ids"] == ["a", "b"]
    assert snapshot["knowledge_unit_ids"] == [1, 2]
    assert snapshot["paper_layout_mode"] == "practice_scroll"
    assert exams_api._exam_config_hash(snapshot) == exams_api._exam_config_hash(dict(reversed(snapshot.items())))


def test_upsert_generated_template_reuses_duplicate_stem_across_units(session: Session) -> None:
    units = _seed_exam_course(session)
    first_unit, second_unit = units[0], units[1]
    existing = exams_api._upsert_generated_template(
        session,
        course_id=COURSE_ID,
        unit=first_unit,
        question_type="single_choice",
        difficulty="easy",
        stem="Which chart best shows parts of a whole?",
        answer="Pie chart",
        explanation="A pie chart shows proportions within one whole.",
        options=["Line chart", "Bar chart", "Pie chart", "Scatter plot"],
        knowledge_unit_refs=[{"knowledge_unit_id": int(first_unit.id or 0), "coverage_weight": 1.0}],
        rationale="first unit",
    )

    reused = exams_api._upsert_generated_template(
        session,
        course_id=COURSE_ID,
        unit=second_unit,
        question_type="single_choice",
        difficulty="medium",
        stem="Which chart best shows parts of a whole?",
        answer="Pie chart",
        explanation="A pie chart is suitable when comparing parts within a total.",
        options=["Line chart", "Bar chart", "Pie chart", "Scatter plot"],
        knowledge_unit_refs=[{"knowledge_unit_id": int(second_unit.id or 0), "coverage_weight": 0.6}],
        rationale="second unit",
    )

    links = exams_api.exams_repo.find_knowledge_unit_links_by_template(session, int(existing.id or 0))

    assert reused.id == existing.id
    assert reused.difficulty == "medium"
    assert {item["knowledge_unit_id"] for item in links} == {int(first_unit.id or 0), int(second_unit.id or 0)}


def test_paper_exam_layout_models_content_flow_and_sections() -> None:
    layout = exams_api._build_paper_layout(
        exam_mode="paper_exam",
        question_count=8,
        paper_layout_mode="gaokao_six_page",
        rows=[
            {"item_order": 1, "question_type": "single_choice", "difficulty": "easy"},
            {"item_order": 2, "question_type": "single_choice", "difficulty": "medium"},
            {"item_order": 3, "question_type": "multiple_choice", "difficulty": "medium"},
            {"item_order": 4, "question_type": "fill_blank", "difficulty": "medium"},
            {"item_order": 5, "question_type": "fill_blank", "difficulty": "hard"},
            {"item_order": 6, "question_type": "short_answer", "difficulty": "medium"},
            {"item_order": 7, "question_type": "short_answer", "difficulty": "hard"},
            {"item_order": 8, "question_type": "short_answer", "difficulty": "hard"},
        ],
    )

    assert layout["mode"] == "gaokao_six_page"
    assert layout["paper_style"] == "gaokao"
    assert layout["pagination_strategy"] == "content_flow"
    assert layout["total_pages"] == 1
    assert layout["pages_per_side"] == 3
    assert layout["sides"] == [{"side_number": 1, "label": "正面", "pages": [1]}]
    assert layout["pages"] == [
        {
            "page_number": 1,
            "question_orders": [1, 2, 3, 4, 5, 6, 7, 8],
            "section_numbers": [1, 2, 3],
        }
    ]
    assert [section["title"] for section in layout["sections"]] == ["一、选择题", "二、填空题", "三、解答题"]
    assert layout["question_allocations"][0]["score"] == 5.0
    assert layout["question_allocations"][-1]["score"] == 14.0


def test_paper_exam_auto_layout_keeps_questions_as_content_flow() -> None:
    layout = exams_api._build_paper_layout(
        exam_mode="paper_exam",
        question_count=24,
        paper_layout_mode="auto",
        rows=[
            {"item_order": order, "question_type": "single_choice", "difficulty": "medium"}
            for order in range(1, 25)
        ],
    )

    assert layout["mode"] == "gaokao_four_page"
    assert layout["paper_style"] == "gaokao"
    assert layout["pagination_strategy"] == "content_flow"
    assert layout["total_pages"] == 1
    assert layout["pages_per_side"] == 2
    assert [len(page["question_orders"]) for page in layout["pages"]] == [24]


def test_exam_preview_helpers_merge_generation_and_failure_states() -> None:
    planned = exams_api._build_blueprint_paper_preview(
        [
            {"item_order": 0, "question_type": "single_choice", "difficulty": "easy", "knowledge_unit_ids": [1]},
            {"item_order": 1, "question_type": "fill_blank", "difficulty": "hard", "knowledge_unit_ids": [2]},
        ],
        question_count=3,
        unit_name_by_id={1: "Matrices", 2: "Eigenvalues"},
    )

    assert [row.order for row in planned.rows] == [1, 2, 3]
    assert [row.generation_status for row in planned.rows] == ["planned", "planned", "planned"]
    assert planned.keywords == ["Matrices", "Eigenvalues"]

    generated = exams_api._merge_generated_question_into_preview(
        planned,
        {
            "item_order": 2,
            "question_type": "multiple_choice",
            "difficulty": "hard",
            "knowledge_unit_refs": [{"knowledge_unit_id": 2, "coverage_weight": 1.0}],
        },
        question_count=3,
        unit_name_by_id={2: "Eigenvalues", 3: "Vectors"},
    )
    failed = exams_api._merge_failed_question_into_preview(
        generated,
        {"item_order": 3, "question_type": "short_answer", "difficulty": "medium"},
        question_count=3,
    )

    assert failed.rows[1].type == "multiple_choice"
    assert failed.rows[1].generation_status == "generated"
    assert failed.rows[2].type == "short_answer"
    assert failed.rows[2].generation_status == "failed"
    assert "multiple_choice" in failed.question_types


def test_exam_generation_context_merges_by_item_order() -> None:
    context: dict[str, object] = {
        "generated_questions": [{"item_order": 2, "stem": "old"}],
        "failed_questions": [{"item_order": 1, "error_message": "old"}],
    }

    exams_api._merge_generated_question_into_context(
        context,
        {"item_order": 1, "stem": "new"},
        question_count=3,
    )
    exams_api._merge_failed_question_into_context(
        context,
        {"item_order": 3, "error_message": "failed"},
        question_count=3,
    )

    assert [item["item_order"] for item in context["generated_questions"]] == [1, 2]
    assert context["generated_question_count"] == 2
    assert [item["item_order"] for item in context["failed_questions"]] == [1, 3]
    assert context["failed_question_count"] == 2


def test_exam_response_helpers_include_generated_items_and_preview_payloads() -> None:
    now = utcnow()
    paper = ExamPaper(
        id=42,
        course_id="course_math00000000",
        user_id="user-1",
        exam_mode="web_practice",
        status="generating",
        total_items=2,
        selection_context_json=json.dumps(
            {
                "generation_status": "generating",
                "generated_questions": [
                    {
                        "item_order": 1,
                        "question_type": "single_choice",
                        "difficulty": "easy",
                        "stem": "Which matrix is invertible?",
                        "options": ["A", "B", "C", "D"],
                        "correct_answer": "A",
                        "explanation": "Because determinant is non-zero.",
                        "knowledge_unit_refs": [{"knowledge_unit_id": 1, "coverage_weight": 0.8}],
                    }
                ],
                "failed_questions": [{"item_order": 2, "error_message": "timeout"}],
            }
        ),
        paper_preview_json=json.dumps(PaperPreview(rows=[]).model_dump(mode="json")),
        created_at=now,
        updated_at=now,
    )

    payload = exams_api._paper_generation_event_payload(
        paper,
        preview=exams_api._build_placeholder_paper_preview(question_count=2),
        stage="generating",
    )
    responses = exams_api._generated_question_item_responses(
        json.loads(paper.selection_context_json),
        knowledge_unit_by_id={1: KnowledgeUnit(id=1, canonical_name="Matrices", knowledge_unit_type="concept")},
        mastery_by_unit_id={1: 0.625},
    )

    assert payload["exam_paper_id"] == 42
    assert payload["status"] == "generating"
    assert payload["generated_question_count"] == 1
    assert payload["failed_question_count"] == 1
    assert payload["stage"] == "generating"
    assert responses[0].id == -1_000_001
    assert responses[0].knowledge_unit_links[0].knowledge_unit_name == "Matrices"
    assert responses[0].knowledge_unit_links[0].mastery_score == 0.625


def test_question_template_response_tolerates_invalid_option_json() -> None:
    now = utcnow()
    template = QuestionTemplate(
        id=5,
        course_id="course_math00000000",
        question_type="single_choice",
        difficulty="easy",
        stem="question stem",
        answer="A",
        explanation="explanation",
        options_json="{broken",
        selection_hints_json='{"rationale":"keep"}',
        template_version=2,
        status="active",
        is_marked=True,
        created_at=now,
        updated_at=now,
    )

    response = exams_api._question_template_response(
        template,
        knowledge_unit_refs=[{"knowledge_unit_id": 1, "coverage_weight": 1.0}],
        has_wrong_attempt=True,
    )

    assert response.options is None
    assert response.selection_hints == {"rationale": "keep"}
    assert response.is_marked is True
    assert response.has_wrong_attempt is True


def test_generated_question_requirement_result_reports_failures() -> None:
    failed_result = SimpleNamespace(
        failed=True,
        error=SimpleNamespace(detail="provider timeout"),
        require_value=lambda: {},
    )

    with pytest.raises(AITeachMeError) as exc_info:
        exams_api._require_generated_questions_by_order(
            build_result=failed_result,
            expected_orders=[1],
        )

    assert exc_info.value.error_code == "EXAM_QUESTION_BUILD_FAILED"
    assert exc_info.value.status_code == 502

    partial_result = SimpleNamespace(
        failed=False,
        error=None,
        require_value=lambda: {
            "generated_questions": [
                {"item_order": 2, "stem": "second"},
                {"item_order": "bad", "stem": "bad"},
            ],
            "failed_questions": [{"item_order": 1, "error_message": "timeout"}],
        },
    )

    generated = exams_api._require_generated_questions_by_order(
        build_result=partial_result,
        expected_orders=[1, 2],
    )

    assert generated == {2: {"item_order": 2, "stem": "second"}}


def test_default_auto_prewarm_config_matches_training_center_default() -> None:
    config = exams_api.default_auto_prewarm_exam_config()

    assert config == {
        "exam_mode": "web_practice",
        "question_count": 24,
        "user_prompt": None,
        "sample_file_ids": [],
        "paper_layout_mode": None,
    }
    assert exams_api.DEFAULT_AUTO_PREWARM_QUESTION_COUNT == 24


def test_prepared_exam_status_and_visibility_boundaries() -> None:
    now = utcnow()
    ready = ExamPaper(status="ready", visibility="hidden", expires_at=now + timedelta(minutes=5))
    stale = ExamPaper(status="ready", visibility="hidden", expires_at=now - timedelta(minutes=1))
    visible = ExamPaper(status="ready", visibility="visible")
    failed = ExamPaper(status="failed", visibility="hidden")

    assert exams_api._is_active_prepared_exam_candidate(ready) is True
    assert exams_api._is_active_prepared_exam_candidate(stale) is False
    assert exams_api._is_active_prepared_exam_candidate(visible) is False
    assert exams_api._prewarm_status_from_candidate(ready) == "ready"
    assert exams_api._prewarm_status_from_candidate(stale) == "stale"
    assert exams_api._prewarm_status_from_candidate(failed) == "failed"
    assert exams_api._prewarm_status_from_candidate(None) == "missing"


@pytest.mark.anyio
async def test_filter_knowledge_units_uses_fallback_when_llm_selection_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cancelled_selection(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(filter_units_node, "select_exam_knowledge_units", cancelled_selection)
    units = [
        KnowledgeUnit(
            id=1,
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name="Matrices",
            normalized_name="matrices",
            summary="Matrix operations and rank.",
            status="active",
        ),
        KnowledgeUnit(
            id=2,
            course_id=COURSE_ID,
            knowledge_unit_type="concept",
            canonical_name="Linear maps",
            normalized_name="linear_maps",
            summary="Linear maps and bases.",
            status="active",
        ),
    ]

    node = filter_units_node.build_filter_knowledge_units_node(context=SimpleNamespace())
    result = await node(
        {
            "course_id": COURSE_ID,
            "course_name": "Linear Algebra",
            "exam_mode": "web_practice",
            "question_count": 2,
            "units": units,
            "priority_unit_ids": [2],
        }
    )

    assert result["error"] == ""
    assert result["filter_strategy"] == "deterministic_cancel_fallback"
    assert result["candidate_unit_ids"] == [2, 1]
    assert [unit.id for unit in result["units"]] == [2, 1]


@pytest.mark.anyio
async def test_exam_prewarm_status_does_not_start_background_generation(
    session: Session,
) -> None:
    _seed_exam_course(session)
    background_tasks = BackgroundTasks()

    response = await exams_api.exam_prewarm_status(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        exam_mode="web_practice",
        num_questions=2,
        user_prompt=None,
        sample_file_ids=None,
        paper_layout_mode=None,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data is not None
    assert response.data.status == "missing"
    assert response.data.background_requested is False
    assert len(background_tasks.tasks) == 0
    assert session.exec(select(ExamPaper)).all() == []


@pytest.mark.anyio
async def test_exam_prewarm_status_retries_cancelled_hidden_failure(
    session: Session,
) -> None:
    units = _seed_exam_course(session)
    unit_ids = [int(unit.id or 0) for unit in units]
    config_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint=exams_api._exam_mastery_fingerprint(session, course_id=COURSE_ID, user_id=USER_ID),
    )
    failed = exams_api._create_exam_generation_paper(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=exams_api._exam_config_hash(config_snapshot),
        visibility="hidden",
        generation_origin="prewarm",
    )
    failed.status = "failed"
    failed.selection_context_json = json.dumps(
        {
            "generation_status": "failed",
            "error_message": "Question candidate filtering was cancelled.",
        },
        ensure_ascii=False,
    )
    session.add(failed)
    session.commit()
    background_tasks = BackgroundTasks()

    class FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def spawn(self, coro, **kwargs):
            self.calls.append(kwargs)
            coro.close()

    registry = FakeRegistry()

    response = await exams_api.exam_prewarm_status(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=registry))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        exam_mode="web_practice",
        num_questions=24,
        user_prompt=None,
        sample_file_ids=None,
        paper_layout_mode=None,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data is not None
    assert response.data.status == "preparing"
    assert response.data.background_requested is True
    assert len(registry.calls) == 1
    assert registry.calls[0]["kind"] == "exam.prewarm"
    assert len(background_tasks.tasks) == 0


@pytest.mark.anyio
async def test_exam_prewarm_status_finds_default_candidate_with_changed_unit_snapshot(
    session: Session,
) -> None:
    units = _seed_exam_course(session)
    partial_unit_ids = [int(units[0].id or 0)]
    partial_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        knowledge_unit_ids=partial_unit_ids,
        mastery_fingerprint=exams_api._exam_mastery_fingerprint(session, course_id=COURSE_ID, user_id=USER_ID),
    )
    exams_api._create_exam_generation_paper(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        unit_ids=partial_unit_ids,
        config_snapshot=partial_snapshot,
        config_hash=exams_api._exam_config_hash(partial_snapshot),
        visibility="hidden",
        generation_origin="prewarm",
    )
    background_tasks = BackgroundTasks()

    response = await exams_api.exam_prewarm_status(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        exam_mode="web_practice",
        num_questions=24,
        user_prompt=None,
        sample_file_ids=None,
        paper_layout_mode=None,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data is not None
    assert response.data.status == "preparing"
    assert response.data.background_requested is False
    assert len(background_tasks.tasks) == 0


@pytest.mark.anyio
async def test_exam_history_does_not_start_default_prewarm(
    session: Session,
) -> None:
    _seed_exam_course(session)
    background_tasks = BackgroundTasks()

    response = await exams_api.exam_history(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        page=1,
        size=20,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data is not None
    assert response.data.items == []
    assert len(background_tasks.tasks) == 0
    assert session.exec(select(ExamPaper)).all() == []


@pytest.mark.anyio
async def test_exam_history_marks_stale_generating_papers_failed(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_exam_course(session)
    stale_at = utcnow() - timedelta(minutes=21)
    fresh_at = utcnow() - timedelta(minutes=5)
    stale_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="generating",
        visibility="visible",
        total_items=24,
        total_score=24.0,
        selection_context_json=json.dumps({"generation_status": "generating"}),
        paper_preview_json=PaperPreview(rows=[]).model_dump_json(),
        created_at=stale_at,
        updated_at=stale_at,
    )
    fresh_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="paper_exam",
        status="generating",
        visibility="visible",
        total_items=24,
        total_score=24.0,
        selection_context_json=json.dumps({"generation_status": "generating"}),
        paper_preview_json=PaperPreview(rows=[]).model_dump_json(),
        created_at=fresh_at,
        updated_at=fresh_at,
    )
    session.add(stale_paper)
    session.add(fresh_paper)
    session.commit()
    session.refresh(stale_paper)
    session.refresh(fresh_paper)
    events: list[tuple[str, int, str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda course_id, paper_id, event, data: events.append((course_id, paper_id, event, data)),
    )

    response = await exams_api.exam_history(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        page=1,
        size=20,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    session.refresh(stale_paper)
    session.refresh(fresh_paper)
    stale_context = json.loads(stale_paper.selection_context_json)
    fresh_context = json.loads(fresh_paper.selection_context_json)
    statuses_by_id = {int(item.id or 0): item.status for item in response.data.items}

    assert stale_paper.status == "failed"
    assert stale_context["generation_status"] == "failed"
    assert stale_context["error_message"] == exams_api.EXAM_GENERATION_STALE_MESSAGE
    assert statuses_by_id[int(stale_paper.id or 0)] == "failed"
    assert fresh_paper.status == "generating"
    assert fresh_context["generation_status"] == "generating"
    assert statuses_by_id[int(fresh_paper.id or 0)] == "generating"
    assert len(events) == 1
    assert events[0][0] == COURSE_ID
    assert events[0][1] == int(stale_paper.id or 0)
    assert events[0][2] == "done"
    assert events[0][3]["status"] == "failed"
    assert events[0][3]["stage"] == "failed"
    assert events[0][3]["error_message"] == exams_api.EXAM_GENERATION_STALE_MESSAGE


@pytest.mark.anyio
async def test_exam_generation_background_persists_progress_items_and_terminal_preview(
    managed_exam_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(managed_exam_session)
    unit_ids = [int(unit.id or 0) for unit in units]
    events: list[tuple[str, int, str, dict[str, object]]] = []
    captured: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(exams_api, "load_course_llm_context", lambda *args, **kwargs: "course context")
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda course_id, paper_id, event, data: events.append((course_id, paper_id, event, data)),
    )
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )

    async def fake_question_build_workflow(**kwargs):
        progress_callback = kwargs["progress_callback"]
        await progress_callback(
            {
                "stage": "filter_exam_units",
                "candidate_unit_ids": [str(unit_ids[0]), unit_ids[1]],
                "candidate_unit_limit": 2,
                "filter_strategy": "weak_first",
            }
        )
        await progress_callback(
            {
                "stage": "plan_question_requirements",
                "question_requirement_plans": [
                    {"item_order": 0, "question_type": "single_choice"},
                    {"item_order": 1, "question_type": "fill_blank"},
                    {"item_order": 2, "question_type": "short_answer"},
                ],
            }
        )
        question_blueprints = [
            {
                "item_order": 0,
                "question_type": "single_choice",
                "difficulty": "easy",
                "knowledge_unit_ids": [unit_ids[0]],
                "rationale": "cover matrix basics",
                "generation_prompt": "Ask matrix invertibility.",
            },
            {
                "item_order": 1,
                "question_type": "fill_blank",
                "difficulty": "medium",
                "knowledge_unit_ids": [unit_ids[1]],
                "rationale": "cover maps",
                "generation_prompt": "Ask map definition.",
            },
            {
                "item_order": 2,
                "question_type": "short_answer",
                "difficulty": "hard",
                "knowledge_unit_ids": [unit_ids[0], unit_ids[1]],
                "rationale": "connect both units",
                "generation_prompt": "Ask synthesis.",
            },
        ]
        generated_questions = [
            {
                "item_order": 1,
                "question_type": "single_choice",
                "difficulty": "easy",
                "stem": "Which matrix is invertible?",
                "options": ["Full rank", "Zero", "Duplicate rows", "Singular"],
                "correct_answer": "Full rank",
                "explanation": "Full rank matrices are invertible in this setting.",
                "knowledge_unit_refs": [{"knowledge_unit_id": unit_ids[0], "coverage_weight": 1.0}],
            },
            {
                "item_order": 2,
                "question_type": "fill_blank",
                "difficulty": "medium",
                "stem": "A linear map preserves {{blank}} and scalar multiplication.",
                "correct_answer": "addition",
                "explanation": "Linearity means preserving vector addition and scalar multiplication.",
                "knowledge_unit_refs": [{"knowledge_unit_id": unit_ids[1], "coverage_weight": 1.0}],
            },
        ]
        failed_questions = [
            {
                "item_order": 3,
                "question_type": "short_answer",
                "difficulty": "hard",
                "knowledge_unit_ids": unit_ids,
                "error_message": "provider timeout",
            }
        ]
        await progress_callback({"stage": "plan_exam_questions", "question_blueprints": question_blueprints})
        await progress_callback(
            {
                "stage": "generate_exam_questions",
                "generated_question": generated_questions[0],
                "generated_question_count": 1,
            }
        )
        await progress_callback(
            {
                "stage": "generate_exam_questions",
                "failed_question": failed_questions[0],
                "failed_question_count": 1,
            }
        )
        return _workflow_result(
            {
                "question_blueprints": question_blueprints,
                "generated_questions": generated_questions,
                "failed_questions": failed_questions,
            }
        )

    monkeypatch.setattr(exams_api, "run_question_build_workflow", fake_question_build_workflow)
    config_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=3,
        user_prompt="matrix practice",
        sample_file_ids=["file-b", "file-a"],
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint="fingerprint",
    )
    paper = exams_api._create_exam_generation_paper(
        managed_exam_session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=3,
        user_prompt="matrix practice",
        sample_file_ids=["file-b", "file-a"],
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=exams_api._exam_config_hash(config_snapshot),
        visibility="visible",
        generation_origin="user",
    )

    await exams_api._run_exam_generation_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=int(paper.id or 0),
        exam_mode="web_practice",
        unit_ids=unit_ids,
        question_count=3,
        user_prompt="matrix practice",
        sample_file_ids=["file-b", "file-a"],
        config_snapshot=config_snapshot,
        config_hash=paper.config_hash,
        schedule_replacement=True,
        background_task_registry=None,
    )

    managed_exam_session.refresh(paper)
    items = exams_api.exams_repo.list_items_by_paper(managed_exam_session, int(paper.id or 0))
    templates = managed_exam_session.exec(select(QuestionTemplate).order_by(QuestionTemplate.id)).all()
    links_by_item_id = exams_api.exams_repo.list_links_for_exam_items(
        managed_exam_session,
        [int(item.id or 0) for item in items],
    )
    preview = PaperPreview.model_validate_json(paper.paper_preview_json)
    context = json.loads(paper.selection_context_json)

    assert paper.status == "ready"
    assert paper.total_items == 2
    assert [item.item_order for item in items] == [1, 2]
    assert [template.stem for template in templates] == [
        "Which matrix is invertible?",
        "A linear map preserves {{blank}} and scalar multiplication.",
    ]
    assert links_by_item_id[int(items[0].id or 0)] == [{"knowledge_unit_id": unit_ids[0], "coverage_weight": 1.0}]
    assert context["failed_questions"][0]["item_order"] == 3
    assert "generated_questions" not in context
    assert context["paper_layout"]["mode"] == "practice_scroll"
    assert context["paper_layout"]["pages"][0]["question_orders"] == [1, 2]
    assert [row.generation_status for row in preview.rows] == ["generated", "generated", "failed"]
    assert any(event == "done" and data["status"] == "ready" for _course, _paper, event, data in events)
    assert captured[0][0] == "exam_generated"
    assert captured[0][1]["course_id"] == COURSE_ID
    assert captured[0][1]["properties"]["exam_mode"] == "web_practice"
    assert captured[0][1]["properties"]["exam_status"] == "ready"
    assert captured[0][1]["properties"]["requested_question_count"] == 3
    assert captured[0][1]["properties"]["sample_file_count"] == 2
    assert captured[0][1]["properties"]["served_from_prepared"] is False
    assert "matrix practice" not in str(captured[0][1]["properties"])


@pytest.mark.anyio
async def test_exam_generation_background_keeps_generated_snapshot_when_final_persistence_fails(
    managed_exam_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(managed_exam_session)
    unit_ids = [int(unit.id or 0) for unit in units]
    events: list[tuple[str, int, str, dict[str, object]]] = []
    generated_questions = [
        {
            "item_order": 1,
            "question_type": "single_choice",
            "difficulty": "easy",
            "stem": "Which matrix is invertible?",
            "options": ["Full rank", "Zero", "Duplicate rows", "Singular"],
            "correct_answer": "Full rank",
            "explanation": "Full rank matrices are invertible in this setting.",
            "knowledge_unit_refs": [{"knowledge_unit_id": unit_ids[0], "coverage_weight": 1.0}],
        },
        {
            "item_order": 2,
            "question_type": "fill_blank",
            "difficulty": "medium",
            "stem": "A linear map preserves {{blank}} and scalar multiplication.",
            "correct_answer": "addition",
            "explanation": "Linearity means preserving vector addition and scalar multiplication.",
            "knowledge_unit_refs": [{"knowledge_unit_id": unit_ids[1], "coverage_weight": 1.0}],
        },
    ]

    monkeypatch.setattr(exams_api, "load_course_llm_context", lambda *args, **kwargs: "course context")
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda course_id, paper_id, event, data: events.append((course_id, paper_id, event, data)),
    )

    async def fake_question_build_workflow(**_kwargs):
        return _workflow_result(
            {
                "generated_questions": generated_questions,
                "failed_questions": [],
                "error": "",
            }
        )

    def fail_template_persistence(*_args, **_kwargs):
        raise RuntimeError("template write failed")

    monkeypatch.setattr(exams_api, "run_question_build_workflow", fake_question_build_workflow)
    monkeypatch.setattr(exams_api, "_upsert_generated_template", fail_template_persistence)
    config_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=2,
        user_prompt="matrix practice",
        sample_file_ids=[],
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint="fingerprint",
    )
    paper = exams_api._create_exam_generation_paper(
        managed_exam_session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=2,
        user_prompt="matrix practice",
        sample_file_ids=[],
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=exams_api._exam_config_hash(config_snapshot),
        visibility="visible",
        generation_origin="user",
    )

    await exams_api._run_exam_generation_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=int(paper.id or 0),
        exam_mode="web_practice",
        unit_ids=unit_ids,
        question_count=2,
        user_prompt="matrix practice",
        sample_file_ids=[],
        config_snapshot=config_snapshot,
        config_hash=paper.config_hash,
    )

    managed_exam_session.refresh(paper)
    context = json.loads(paper.selection_context_json)
    detail = exams_api._paper_detail(managed_exam_session, paper)

    assert paper.status == "failed"
    assert context["generated_question_count"] == 2
    assert [item["item_order"] for item in context["generated_questions"]] == [1, 2]
    assert detail.status == "failed"
    assert [item.item_order for item in detail.items] == [1, 2]
    assert detail.items[0].stem == "Which matrix is invertible?"
    assert any(
        event == "snapshot"
        and data.get("stage") == "generate_exam_questions"
        and data.get("generated_question_count") == 2
        for _course, _paper, event, data in events
    )
    assert events[-1][2] == "done"
    assert events[-1][3]["status"] == "failed"


@pytest.mark.anyio
async def test_exam_generation_background_marks_failed_when_units_are_missing(
    managed_exam_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_exam_course(managed_exam_session, with_units=False)
    events: list[tuple[str, dict[str, object]]] = []
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda _course_id, _paper_id, event, data: events.append((event, data)),
    )
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )
    config_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=1,
        user_prompt=None,
        sample_file_ids=[],
        knowledge_unit_ids=[999],
        mastery_fingerprint="fingerprint",
    )
    paper = exams_api._create_exam_generation_paper(
        managed_exam_session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=1,
        user_prompt=None,
        sample_file_ids=[],
        unit_ids=[999],
        config_snapshot=config_snapshot,
        config_hash=exams_api._exam_config_hash(config_snapshot),
        visibility="visible",
        generation_origin="user",
    )

    await exams_api._run_exam_generation_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=int(paper.id or 0),
        exam_mode="web_practice",
        unit_ids=[999],
        question_count=1,
        config_snapshot=config_snapshot,
        config_hash=paper.config_hash,
        user_prompt=None,
    )

    managed_exam_session.refresh(paper)
    context = json.loads(paper.selection_context_json)

    assert paper.status == "failed"
    assert context["generation_status"] == "failed"
    assert "No persisted KnowledgeUnits" in context["error_message"]
    assert events[-1][0] == "done"
    assert events[-1][1]["status"] == "failed"
    assert all(event != "exam_generated" for event, _kwargs in captured)


@pytest.mark.anyio
async def test_generate_exam_endpoint_creates_paper_and_schedules_background(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(session)
    background_tasks = BackgroundTasks()
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )
    response = await exams_api.generate_exam(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        body=ExamGenerateRequest(
            exam_mode="web_practice",
            user_prompt="  focus on matrices  ",
            sample_file_ids=["file-b", "file-a"],
            num_questions=2,
        ),
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )
    papers = session.exec(select(ExamPaper)).all()

    assert response.data is not None
    assert response.data.status == "generating"
    assert response.data.num_questions == 2
    assert response.data.sample_file_ids == ["file-b", "file-a"]
    assert response.data.served_from_prepared is False
    assert len(background_tasks.tasks) == 1
    assert len(papers) == 1
    assert json.loads(papers[0].config_snapshot_json)["knowledge_unit_ids"] == [
        int(unit.id or 0) for unit in units
    ]
    assert captured[0][0] == "exam_generation_requested"
    assert captured[0][1]["course_id"] == COURSE_ID
    assert captured[0][1]["properties"]["exam_mode"] == "web_practice"
    assert captured[0][1]["properties"]["requested_question_count"] == 2
    assert "focus on matrices" not in str(captured[0][1]["properties"])


@pytest.mark.anyio
async def test_generate_exam_endpoint_claims_prepared_paper(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(session)
    unit_ids = [int(unit.id or 0) for unit in units]
    background_tasks = BackgroundTasks()
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )
    config_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=2,
        user_prompt="focus on matrices",
        sample_file_ids=["file-b", "file-a"],
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint=exams_api._exam_mastery_fingerprint(session, course_id=COURSE_ID, user_id=USER_ID),
    )
    prepared = exams_api._create_exam_generation_paper(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=2,
        user_prompt="focus on matrices",
        sample_file_ids=["file-b", "file-a"],
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=exams_api._exam_config_hash(config_snapshot),
        visibility="hidden",
        generation_origin="prewarm",
    )
    prepared.status = "ready"
    prepared.total_items = 2
    session.add(prepared)
    session.commit()

    response = await exams_api.generate_exam(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        body=ExamGenerateRequest(
            exam_mode="web_practice",
            user_prompt="  focus on matrices  ",
            sample_file_ids=["file-b", "file-a"],
            num_questions=2,
        ),
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )
    session.refresh(prepared)
    visible_papers = session.exec(select(ExamPaper).where(ExamPaper.visibility == "visible")).all()

    assert response.data is not None
    assert response.data.exam_paper_id == prepared.id
    assert response.data.status == "ready"
    assert response.data.num_questions == 2
    assert response.data.served_from_prepared is True
    assert prepared.visibility == "visible"
    assert prepared.generation_origin == "prewarm"
    assert len(visible_papers) == 1
    assert len(background_tasks.tasks) == 0
    assert captured[0][0] == "exam_generation_requested"
    assert captured[0][1]["properties"]["served_from_prepared"] is True
    assert captured[1][0] == "exam_generated"
    assert captured[1][1]["properties"]["served_from_prepared"] is True


@pytest.mark.anyio
async def test_generate_exam_endpoint_claims_default_prewarm_with_changed_unit_snapshot(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(session)
    partial_unit_ids = [int(units[0].id or 0)]
    background_tasks = BackgroundTasks()
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )
    partial_snapshot = exams_api._build_exam_config_snapshot(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        knowledge_unit_ids=partial_unit_ids,
        mastery_fingerprint=exams_api._exam_mastery_fingerprint(session, course_id=COURSE_ID, user_id=USER_ID),
    )
    prepared = exams_api._create_exam_generation_paper(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        question_count=24,
        user_prompt=None,
        sample_file_ids=[],
        unit_ids=partial_unit_ids,
        config_snapshot=partial_snapshot,
        config_hash=exams_api._exam_config_hash(partial_snapshot),
        visibility="hidden",
        generation_origin="prewarm",
    )

    response = await exams_api.generate_exam(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        body=ExamGenerateRequest(
            exam_mode="web_practice",
            user_prompt=None,
            sample_file_ids=[],
            num_questions=24,
        ),
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )
    session.refresh(prepared)
    visible_papers = session.exec(select(ExamPaper).where(ExamPaper.visibility == "visible")).all()

    assert response.data is not None
    assert response.data.exam_paper_id == prepared.id
    assert response.data.status == "generating"
    assert response.data.num_questions == 24
    assert response.data.served_from_prepared is True
    assert prepared.visibility == "visible"
    assert prepared.generation_origin == "prewarm"
    assert len(visible_papers) == 1
    assert len(background_tasks.tasks) == 0
    assert [event for event, _ in captured] == ["exam_generation_requested"]
    assert captured[0][1]["properties"]["served_from_prepared"] is True


@pytest.mark.anyio
async def test_submit_exam_endpoint_captures_submit_and_grade_events(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_exam_course(session, with_units=False)
    template_a = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="fill_blank",
        difficulty="easy",
        stem="A matrix with nonzero determinant is {{blank}}.",
        stem_hash="analytics-submit-a",
        answer="invertible",
        explanation="Nonzero determinant implies invertibility.",
    )
    template_b = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="true_false",
        difficulty="easy",
        stem="Every square matrix is invertible.",
        stem_hash="analytics-submit-b",
        answer="False",
        explanation="Singular square matrices are not invertible.",
    )
    session.add_all([template_a, template_b])
    session.commit()
    session.refresh(template_a)
    session.refresh(template_b)

    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="ready",
        total_items=2,
        total_score=2.0,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    session.add_all(
        [
            ExamPaperItem(
                exam_paper_id=int(paper.id or 0),
                question_template_id=int(template_a.id or 0),
                item_order=1,
                stem_snapshot=template_a.stem,
                answer_snapshot=template_a.answer,
                explanation_snapshot=template_a.explanation,
                difficulty=template_a.difficulty,
                question_type=template_a.question_type,
                score=1.0,
            ),
            ExamPaperItem(
                exam_paper_id=int(paper.id or 0),
                question_template_id=int(template_b.id or 0),
                item_order=2,
                stem_snapshot=template_b.stem,
                answer_snapshot=template_b.answer,
                explanation_snapshot=template_b.explanation,
                difficulty=template_b.difficulty,
                question_type=template_b.question_type,
                score=1.0,
            ),
        ]
    )
    session.commit()

    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        exams_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )

    async def fake_run_exam_grade_workflow(**_kwargs):
        return [
            ExamItemGradeDecision(
                is_correct=True,
                score_obtained=1.0,
                score_max=1.0,
                feedback_text="Correct.",
                error_cause_label=None,
                grading_mode="objective_rule",
            ),
            ExamItemGradeDecision(
                is_correct=False,
                score_obtained=0.0,
                score_max=1.0,
                feedback_text="Incorrect.",
                error_cause_label="concept_gap",
                grading_mode="objective_rule",
            ),
        ]

    async def fake_profile_update_workflow(**_kwargs):
        return _workflow_result(
            {
                "mastery_result": {"states_updated": 1},
                "review_task_ids": ["review-1"],
            }
        )

    monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fake_run_exam_grade_workflow)
    monkeypatch.setattr(exams_api, "run_profile_update_workflow", fake_profile_update_workflow)

    response = await exams_api.submit_exam(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        exam_paper_id=int(paper.id or 0),
        body=ExamSubmitRequest(
                answers=[
                    {"item_order": 1, "answer": "invertible"},
                    {"item_order": 2, "answer": "submitted_false_choice_sentinel"},
                ]
            ),
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )

    assert response.data.score == 1.0
    assert [event for event, _kwargs in captured] == ["exam_submitted", "exam_graded"]
    submitted_properties = captured[0][1]["properties"]
    graded_properties = captured[1][1]["properties"]
    assert submitted_properties["answer_count"] == 2
    assert submitted_properties["answered_count"] == 2
    assert graded_properties["score_obtained"] == 1.0
    assert graded_properties["total_score"] == 2.0
    assert graded_properties["states_updated"] == 1
    assert "invertible" not in str(submitted_properties)
    assert "submitted_false_choice_sentinel" not in str(graded_properties)


def test_exam_question_draft_normalizes_choice_and_unit_refs() -> None:
    draft = generator.ExamQuestionDraft.model_validate(
        {
            "item_order": 1,
            "question_type": "single_choice",
            "difficulty": "easy",
            "stem": "Choose the invertible matrix from the list below.",
            "options": {"B": "B. Singular matrix", "A": "A. Full rank matrix", "D": "D. Zero matrix", "C": "C. Duplicate rows"},
            "correct_answer": "Full rank matrix",
            "explanation": "The full rank matrix has a non-zero determinant.",
            "knowledge_unit_refs": "knowledge_unit_id:1 coverage_weight:0.7; knowledge_unit_id:2 weight:0.3",
        }
    )

    assert draft.options == ["Full rank matrix", "Singular matrix", "Duplicate rows", "Zero matrix"]
    assert draft.correct_answer == "A"
    assert draft.correct_indices == [0]
    assert [ref.knowledge_unit_id for ref in draft.knowledge_unit_refs] == [1, 2]


def test_exam_question_draft_preserves_fenced_code_indentation() -> None:
    draft = generator.ExamQuestionDraft.model_validate(
        {
            "item_order": 1,
            "question_type": "single_choice",
            "difficulty": "medium",
            "stem": (
                "阅读下面的函数，判断它返回什么。\n\n"
                "```python\n"
                "def total_score(items):\n"
                "    total = 0\n"
                "    for item in items:\n"
                "        total += item\n"
                "    return total\n"
                "```"
            ),
            "options": [
                "A. ```python\nresult = total_score([1, 2, 3])\nprint(result)\n```",
                "返回列表长度",
                "语法错误",
                "返回 None",
            ],
            "correct_indices": [0],
            "explanation": "函数体和循环体缩进有效，循环会逐项累加。",
            "knowledge_unit_id": 1,
        }
    )
    answer_draft = generator.ExamQuestionDraft.model_validate(
        {
            "item_order": 2,
            "question_type": "short_answer",
            "difficulty": "medium",
            "stem": "写出一个包含条件分支的最小 Python 函数示例。",
            "correct_answer": (
                "```python\n"
                "def is_positive(value):\n"
                "    if value > 0:\n"
                "        return True\n"
                "    return False\n"
                "```"
            ),
            "explanation": "函数体、if 分支和 return 都需要保留缩进。",
            "knowledge_unit_id": 1,
        }
    )

    assert "\n    total = 0" in draft.stem
    assert "\n        total += item" in draft.stem
    assert draft.options is not None
    assert draft.options[0].startswith("```python\n")
    assert "\nprint(result)\n```" in draft.options[0]
    assert draft.correct_answer == "A"
    assert "\n    if value > 0:" in answer_draft.correct_answer
    assert "\n        return True" in answer_draft.correct_answer


def test_exam_question_draft_rejects_invalid_shapes() -> None:
    with pytest.raises(ValidationError, match="single_choice questions must contain exactly 4 options"):
        generator.ExamQuestionDraft.model_validate(
            {
                "item_order": 1,
                "question_type": "single_choice",
                "difficulty": "easy",
                "stem": "Choose the invertible matrix from the list below.",
                "options": ["A", "B"],
                "correct_indices": [0],
                "explanation": "A valid explanation for this generated item.",
                "knowledge_unit_id": 1,
            }
        )

    with pytest.raises(ValidationError, match="non-choice questions must not provide options"):
        generator.ExamQuestionDraft.model_validate(
            {
                "item_order": 2,
                "question_type": "fill_blank",
                "difficulty": "medium",
                "stem": "The determinant of identity matrix is {{blank}}.",
                "options": ["one", "zero", "two", "three"],
                "correct_answer": "one",
                "explanation": "The identity matrix has determinant one.",
                "knowledge_unit_id": 1,
            }
        )


def test_exam_question_generation_models_normalize_plans_and_weights() -> None:
    blueprints = generator.ExamQuestionBlueprintBatch.model_validate(
        {
            "blueprints": [
                {"item_order": 0, "knowledge_unit_ids": 1, "question_type": "single_choice", "difficulty": "easy"},
                {"item_order": 1, "knowledge_unit_ids": [1, 2, 2], "question_type": "fill_blank", "difficulty": "hard"},
            ]
        }
    )
    requirement_batch = generator.ExamQuestionRequirementBatch.model_validate(
        {
            "rationale": "  cover weak units   first  ",
            "prompts": [
                {"item_order": 0, "question_type": "single_choice", "generation_prompt": "  ask concept  "},
                {"item_order": 1, "question_type": "fill_blank", "generation_prompt": "ask recall"},
            ],
        }
    )
    refs = generator._normalize_weight_refs(
        [
            generator.ExamQuestionUnitRef(knowledge_unit_id=2, coverage_weight=1),
            generator.ExamQuestionUnitRef(knowledge_unit_id=1, coverage_weight=1),
            generator.ExamQuestionUnitRef(knowledge_unit_id=99, coverage_weight=1),
        ],
        allowed_unit_ids=[1, 2],
    )

    assert [item.item_order for item in blueprints.blueprints] == [1, 2]
    assert blueprints.blueprints[0].to_generation_spec().knowledge_unit_ids == [1]
    assert [item.item_order for item in requirement_batch.prompts] == [1, 2]
    assert requirement_batch.rationale == "cover weak units first"
    assert [(ref.knowledge_unit_id, ref.coverage_weight) for ref in refs] == [(2, 0.5), (1, 0.5)]


def test_exam_generator_validation_helpers_detect_alignment_errors() -> None:
    spec = generator.ExamQuestionGenerationSpec(
        item_order=1,
        knowledge_unit_id=1,
        knowledge_unit_ids=[1],
        question_type="single_choice",
        difficulty="easy",
    )
    draft = generator.ExamQuestionDraft(
        item_order=1,
        question_type="single_choice",
        difficulty="easy",
        stem="Choose the invertible matrix from the list below.",
        options=["Full rank", "Zero", "Duplicate", "Singular"],
        correct_indices=[0],
        explanation="The full rank matrix has a non-zero determinant.",
        knowledge_unit_refs=[generator.ExamQuestionUnitRef(knowledge_unit_id=1, coverage_weight=1)],
    )

    assert generator._validate_batch_alignment(generated=[draft], requested_specs=[spec]) == [draft]

    mismatched = draft.model_copy(update={"question_type": "fill_blank"})
    with pytest.raises(ValueError, match="question_type"):
        generator._validate_batch_alignment(generated=[mismatched], requested_specs=[spec])

    with pytest.raises(ValueError, match="incomplete batch"):
        generator._validate_batch_alignment(generated=[], requested_specs=[spec])


def test_question_build_generate_one_policy_caps_retries_and_timeout() -> None:
    kwargs = question_build_completion_kwargs(QuestionBuildModelStep.GENERATE_ONE, attempt=1)

    assert kwargs["timeout"] == 120
    assert kwargs["max_retries"] == 1


@pytest.mark.anyio
async def test_generate_exam_questions_enforces_per_item_total_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator, "_QUESTION_GENERATION_TOTAL_TIMEOUT_S", 0.01)

    async def fake_generate_one_exam_question(**kwargs):
        spec = kwargs["spec"]
        if spec.item_order == 1:
            await asyncio.sleep(1)
        return generator.ExamQuestionDraft(
            item_order=spec.item_order,
            question_type=spec.question_type,
            difficulty=spec.difficulty,
            stem="Choose the invertible matrix from the list below.",
            options=["Full rank", "Zero", "Duplicate rows", "Singular"],
            correct_indices=[0],
            explanation="The full rank matrix has a non-zero determinant.",
            knowledge_unit_refs=[
                generator.ExamQuestionUnitRef(knowledge_unit_id=1, coverage_weight=1),
            ],
        )

    monkeypatch.setattr(generator, "_generate_one_exam_question", fake_generate_one_exam_question)
    failures: list[generator.ExamQuestionGenerationFailure] = []

    async def record_failure(failure: generator.ExamQuestionGenerationFailure) -> None:
        failures.append(failure)

    questions = await generator.generate_exam_questions_for_units(
        units=[
            KnowledgeUnit(
                id=1,
                course_id=COURSE_ID,
                knowledge_unit_type="concept",
                canonical_name="Matrices",
                normalized_name="matrices",
                summary="Matrix operations and rank.",
                status="active",
            ),
        ],
        specs=[
            generator.ExamQuestionGenerationSpec(
                item_order=1,
                knowledge_unit_id=1,
                knowledge_unit_ids=[1],
                question_type="single_choice",
                difficulty="easy",
            ),
            generator.ExamQuestionGenerationSpec(
                item_order=2,
                knowledge_unit_id=1,
                knowledge_unit_ids=[1],
                question_type="single_choice",
                difficulty="easy",
            ),
        ],
        on_question_failed=record_failure,
        allow_partial=True,
    )

    assert [question.item_order for question in questions] == [2]
    assert [failure.item_order for failure in failures] == [1]
    assert "timed out after 0.01s" in failures[0].error_message
