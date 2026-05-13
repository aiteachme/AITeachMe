from __future__ import annotations

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
from app.schemas.exams import ExamGenerateRequest, PaperPreview
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.examine.question_build.lib import generator


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
    assert exams_api._exam_config_hash(snapshot) == exams_api._exam_config_hash(dict(reversed(snapshot.items())))


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
async def test_exam_generation_background_persists_progress_items_and_terminal_preview(
    managed_exam_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _seed_exam_course(managed_exam_session)
    unit_ids = [int(unit.id or 0) for unit in units]
    events: list[tuple[str, int, str, dict[str, object]]] = []

    monkeypatch.setattr(exams_api, "load_course_llm_context", lambda *args, **kwargs: "course context")
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda course_id, paper_id, event, data: events.append((course_id, paper_id, event, data)),
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
    assert [row.generation_status for row in preview.rows] == ["generated", "generated", "failed"]
    assert any(event == "done" and data["status"] == "ready" for _course, _paper, event, data in events)


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
    monkeypatch.setattr(
        exams_api,
        "_publish_exam_event",
        lambda _course_id, _paper_id, event, data: events.append((event, data)),
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


@pytest.mark.anyio
async def test_generate_exam_endpoint_creates_paper_and_schedules_background(session: Session) -> None:
    units = _seed_exam_course(session)
    background_tasks = BackgroundTasks()
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
    assert len(background_tasks.tasks) == 1
    assert len(papers) == 1
    assert json.loads(papers[0].config_snapshot_json)["knowledge_unit_ids"] == [
        int(unit.id or 0) for unit in units
    ]


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
