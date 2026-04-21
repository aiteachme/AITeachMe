"""Exams API endpoints."""

from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import ExamPaper, ExamPaperItem, QuestionTemplate, exam_mode_value
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.repositories import exams_repo
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, PageParams, PaginatedData, build_paginated_data, ok_response
from app.schemas.exams import (
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamGradeResponse,
    ExamHistoryItem,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    ExamSubmitRequest,
)
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.examine import (
    ExamQuestionGenerationSpec,
    run_question_build_workflow,
)
from app.workflows.profile import schedule_reviews, update_mastery_from_exam

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _ensure_subject(session: Session, subject: str, user_id: str) -> Subject:
    record = session.exec(select(Subject).where(Subject.slug == subject, Subject.user_id == user_id)).first()
    if record is None:
        _raise_not_found(f"Subject `{subject}` not found.", error_code="SUBJECT_NOT_FOUND")
    return record


def _json_list(raw: str | None) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _hash_stem(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()


def _raise_not_found(detail: str, error_code: str = "EXAM_NOT_FOUND") -> None:
    raise AITeachMeError(detail=detail, error_code=error_code, status_code=404)


def _clean_exam_text(value: str | None) -> str:
    text = str(value or "")
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _is_exam_eligible_unit(unit: KnowledgeUnit) -> bool:
    name = _clean_exam_text(unit.canonical_name)
    summary = _clean_exam_text(unit.summary)
    if not name or len(name) <= 1:
        return False
    if len(name) > 80:
        return False
    if summary and len(summary) > 1000:
        return False
    return True


def _pick_knowledge_units(
    session: Session,
    *,
    user_id: str,
    subject: str,
    exam_mode: str,
    focus_prompt: str | None,
    limit: int,
) -> list[KnowledgeUnit]:
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.status == "active",
    )
    units = list(session.exec(stmt.order_by(KnowledgeUnit.id)).all())
    units = [unit for unit in units if _is_exam_eligible_unit(unit)]
    units_by_id = {unit.id: unit for unit in units if unit.id is not None}
    ordered_units: list[KnowledgeUnit] = []

    if exam_mode == "web_practice":
        due_states = profile_repo.list_due_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            as_of=utcnow(),
            target_kind="knowledge_unit",
        )
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        for state in [*due_states, *weak_states]:
            knowledge_unit_id = state.knowledge_unit_id
            if knowledge_unit_id is None:
                continue
            unit = units_by_id.get(int(knowledge_unit_id))
            if unit is not None and unit not in ordered_units:
                ordered_units.append(unit)

    if exam_mode == "paper_exam":
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        weak_ids = {
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        }
        strong_units = [unit for unit in units if unit.id not in weak_ids]
        weak_units = [unit for unit in units if unit.id in weak_ids]
        ordered_units.extend(weak_units[: max(1, limit // 2)])
        ordered_units.extend([unit for unit in strong_units if unit not in ordered_units])

    if not ordered_units:
        ordered_units = units[:]

    focus = (focus_prompt or "").strip().casefold()
    if focus:
        focused = [
            unit
            for unit in ordered_units
            if focus in unit.canonical_name.casefold()
            or focus in (unit.summary or "").casefold()
            or focus in unit.knowledge_unit_type.casefold()
        ]
        if focused:
            ordered_units = focused

    deduped: list[KnowledgeUnit] = []
    seen_ids: set[int] = set()
    for unit in ordered_units:
        if unit.id is None or unit.id in seen_ids:
            continue
        seen_ids.add(unit.id)
        deduped.append(unit)
    return deduped[: max(1, limit)]


def _question_type_for_order(*, exam_mode: str, difficulty: str, item_order: int) -> str:
    if exam_mode == "paper_exam":
        cycle = ["single_choice", "fill_blank", "short_answer"]
    elif difficulty == "easy":
        cycle = ["single_choice", "fill_blank"]
    elif difficulty == "hard":
        cycle = ["short_answer", "fill_blank", "single_choice"]
    else:
        cycle = ["single_choice", "short_answer", "fill_blank"]
    return cycle[(item_order - 1) % len(cycle)]


def _difficulty_for_order(*, requested_difficulty: str, item_order: int) -> str:
    normalized = str(requested_difficulty or "medium").strip().lower()
    if normalized in {"easy", "medium", "hard"}:
        return normalized
    if normalized == "mixed":
        cycle = ["easy", "medium", "hard"]
        return cycle[(item_order - 1) % len(cycle)]
    return "medium"


def _upsert_generated_template(
    session: Session,
    *,
    subject: str,
    unit: KnowledgeUnit,
    question_type: str,
    difficulty: str,
    stem: str,
    answer: str,
    explanation: str,
    options: list[str] | None,
) -> QuestionTemplate:
    stem_hash = _hash_stem(stem)
    existing = session.exec(
        select(QuestionTemplate).where(
            QuestionTemplate.subject == subject,
            QuestionTemplate.knowledge_unit_id == unit.id,
            QuestionTemplate.stem_hash == stem_hash,
            QuestionTemplate.status == "active",
        )
    ).first()
    if existing is not None:
        existing.question_type = question_type
        existing.difficulty = difficulty
        existing.stem = stem
        existing.answer = answer
        existing.explanation = explanation
        existing.options_json = json.dumps(options, ensure_ascii=False) if options else None
        existing.knowledge_unit_refs_json = json.dumps(
            [{"knowledge_unit_id": unit.id, "coverage_weight": 1.0, "role": "primary"}],
            ensure_ascii=False,
        )
        existing.updated_at = utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    template = QuestionTemplate(
        subject=subject,
        knowledge_unit_id=unit.id,
        question_type=question_type,
        difficulty=difficulty,
        stem=stem,
        stem_hash=stem_hash,
        answer=answer,
        explanation=explanation,
        options_json=json.dumps(options, ensure_ascii=False) if options else None,
        knowledge_unit_refs_json=json.dumps(
            [{"knowledge_unit_id": unit.id, "coverage_weight": 1.0, "role": "primary"}],
            ensure_ascii=False,
        ),
    )
    return exams_repo.create_question_template(session, template)


def _paper_item_response(
    item: ExamPaperItem,
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    mastery_by_unit_id: dict[int, float],
) -> ExamPaperItemResponse:
    return ExamPaperItemResponse(
        id=item.id,
        item_order=item.item_order,
        question_template_id=item.question_template_id,
        question_type=item.question_type,
        difficulty=item.difficulty,
        stem=item.stem_snapshot,
        options=json.loads(item.options_snapshot_json) if item.options_snapshot_json else None,
        correct_answer=item.answer_snapshot,
        explanation=item.explanation_snapshot,
        knowledge_unit_links=[
            {
                "knowledge_unit_id": knowledge_unit_id,
                "knowledge_unit_name": (
                    knowledge_unit_by_id[knowledge_unit_id].canonical_name
                    if knowledge_unit_id in knowledge_unit_by_id
                    else ""
                ),
                "coverage_weight": float(ref.get("coverage_weight", 1.0) or 1.0),
                "role": str(ref.get("role", "primary")),
                "mastery_score": mastery_by_unit_id.get(knowledge_unit_id),
            }
            for ref in _json_list(item.knowledge_unit_refs_json)
            for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
            if knowledge_unit_id > 0
        ],
        user_answer=item.answer_content or None,
        is_correct=item.is_correct,
        score_obtained=item.score_obtained,
        score_max=item.score_max,
        error_cause_label=item.error_cause_label,
    )


def _paper_detail(session: Session, paper: ExamPaper) -> ExamPaperDetailResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    knowledge_unit_ids = {
        knowledge_unit_id
        for item in items
        for ref in _json_list(item.knowledge_unit_refs_json)
        for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
        if knowledge_unit_id > 0
    }
    knowledge_unit_by_id = {
        unit.id: unit
        for unit in session.exec(
            select(KnowledgeUnit).where(KnowledgeUnit.id.in_(knowledge_unit_ids))
        ).all()
        if unit.id is not None
    } if knowledge_unit_ids else {}
    mastery_by_unit_id = {
        int(state.knowledge_unit_id): state.mastery_score
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=paper.user_id,
            subject=paper.subject,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }
    return ExamPaperDetailResponse(
        id=paper.id,
        subject=paper.subject,
        user_id=paper.user_id,
        exam_mode=paper.exam_mode,
        status=paper.status,
        total_items=paper.total_items,
        score_obtained=paper.score_obtained,
        total_score=paper.total_score,
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
        created_at=paper.created_at,
        selection_context=json.loads(paper.selection_context_json or "{}"),
        items=[
            _paper_item_response(
                item,
                knowledge_unit_by_id=knowledge_unit_by_id,
                mastery_by_unit_id=mastery_by_unit_id,
            )
            for item in items
        ],
    )


def _grade_exam(session: Session, paper: ExamPaper) -> ExamGradeResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    total_score = 0.0
    score_obtained = 0.0
    now = utcnow()
    for item in items:
        expected = " ".join((item.answer_snapshot or "").casefold().split())
        answer = " ".join((item.answer_content or "").casefold().split())
        is_correct = bool(answer and (answer == expected or answer in expected or expected in answer))
        item.is_correct = is_correct
        item.score_max = item.score
        item.score_obtained = item.score if is_correct else 0.0
        item.error_cause_label = None if is_correct else "knowledge_gap"
        item.feedback_text = "Correct." if is_correct else "Review the linked KnowledgeUnit and try again."
        item.graded_at = now
        item.updated_at = now
        total_score += item.score
        score_obtained += item.score_obtained or 0.0
        session.add(item)

    paper.status = "graded"
    paper.total_score = total_score
    paper.score_obtained = score_obtained
    paper.graded_at = now
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)

    mastery = update_mastery_from_exam(session, paper.id or 0)
    reviews = schedule_reviews(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        updated_state_ids=mastery.updated_state_ids,
    )
    return ExamGradeResponse(
        id=paper.id or 0,
        status="completed",
        error_message=None,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        exam_paper_id=paper.id or 0,
        score=score_obtained,
        states_updated=mastery.states_updated,
        tasks_created=len(reviews),
        mastery_consumed=True,
    )


@router.post(
    "/generate",
    response_model=ApiResponse[ExamGenerateResponse],
    summary="Generate an exam from KnowledgeUnits",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def generate_exam(
    subject: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    question_count = max(1, int(body.num_questions or 5))
    units = _pick_knowledge_units(
        session,
        user_id=user.user_id,
        subject=normalized,
        exam_mode=body.exam_mode,
        focus_prompt=body.focus_prompt,
        limit=question_count,
    )
    if not units:
        raise AITeachMeError(
            detail="No active KnowledgeUnits are available for exam generation.",
            error_code="NO_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )

    mode = exam_mode_value(body.exam_mode)
    requested_difficulty = body.difficulty or "medium"
    question_specs = [
        ExamQuestionGenerationSpec(
            item_order=order,
            knowledge_unit_id=int(unit.id or 0),
            question_type=_question_type_for_order(
                exam_mode=mode,
                difficulty=_difficulty_for_order(
                    requested_difficulty=requested_difficulty,
                    item_order=order,
                ),
                item_order=order,
            ),
            difficulty=_difficulty_for_order(
                requested_difficulty=requested_difficulty,
                item_order=order,
            ),
        )
        for order, unit in enumerate(units, start=1)
        if unit.id is not None
    ]
    build_result = await run_question_build_workflow(
        subject=normalized,
        exam_mode=mode,
        units=units,
        specs=question_specs,
        focus_prompt=body.focus_prompt or "",
        user_prompt=body.user_prompt or "",
        style_prompt=body.style_prompt or "",
    )
    generated_questions = build_result.require_value().get("generated_questions") or []

    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            status="ready",
            total_items=len(units),
            total_score=float(len(units)),
            selection_context_json=json.dumps(
                {
                    "source": "knowledge_unit_llm",
                    "knowledge_unit_ids": [unit.id for unit in units],
                    "focus_prompt": body.focus_prompt,
                    "user_prompt": body.user_prompt,
                    "style_prompt": body.style_prompt,
                    "requested_difficulty": requested_difficulty,
                    "sample_file_uids": body.sample_file_uids or [],
                },
                ensure_ascii=False,
            ),
        ),
    )
    items: list[ExamPaperItem] = []
    generated_by_order = {int(item["item_order"]): item for item in generated_questions}
    for order, unit in enumerate(units, start=1):
        generated = generated_by_order[order]
        template = _upsert_generated_template(
            session,
            subject=normalized,
            unit=unit,
            difficulty=str(generated["difficulty"]),
            question_type=str(generated["question_type"]),
            stem=str(generated["stem"]),
            answer=str(generated["correct_answer"]),
            explanation=str(generated["explanation"]),
            options=list(generated.get("options") or []) or None,
        )
        items.append(
            ExamPaperItem(
                exam_paper_id=paper.id or 0,
                question_template_id=template.id or 0,
                item_order=order,
                stem_snapshot=template.stem,
                options_snapshot_json=template.options_json,
                answer_snapshot=template.answer,
                explanation_snapshot=template.explanation,
                knowledge_unit_id=unit.id,
                knowledge_unit_refs_json=template.knowledge_unit_refs_json,
                difficulty=template.difficulty,
                question_type=template.question_type,
                score=1.0,
            )
        )
    exams_repo.create_exam_paper_items(session, items)
    return ok_response(
        ExamGenerateResponse(
            id=paper.id or 0,
            status=paper.status,
            error_message=None,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
            subject=paper.subject,
            user_id=paper.user_id,
            exam_mode=paper.exam_mode,
            num_questions=len(items),
            exam_paper_id=paper.id,
            sample_file_uids=body.sample_file_uids or [],
        )
    )


@router.get(
    "/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="List exam history",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_history(
    subject: str = Path(...),
    page: int = 1,
    size: int = 20,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows, total = exams_repo.list_exam_papers(
        session,
        subject=normalized,
        user_id=user.user_id,
        limit=size,
        offset=PageParams(page=page, size=size).offset,
    )
    return ok_response(
        build_paginated_data(
            items=[
                ExamHistoryItem(
                    id=paper.id,
                    subject=paper.subject,
                    user_id=paper.user_id,
                    exam_mode=paper.exam_mode,
                    status=paper.status,
                    total_items=paper.total_items,
                    score_obtained=paper.score_obtained,
                    total_score=paper.total_score,
                    created_at=paper.created_at,
                    submitted_at=paper.submitted_at,
                    graded_at=paper.graded_at,
                )
                for paper in rows
            ],
            page=page,
            size=size,
            total=total,
        )
    )


@router.get(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Fetch exam detail",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_detail(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    return ok_response(_paper_detail(session, paper))


@router.post(
    "/{exam_paper_id}/submit",
    response_model=ApiResponse[ExamGradeResponse],
    summary="Submit answers and update KnowledgeUnit mastery",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def submit_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    body: ExamSubmitRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status == "graded":
        raise AITeachMeError(detail="Exam already graded.", error_code="EXAM_ALREADY_GRADED", status_code=409)

    answer_by_id = {item.exam_paper_item_id: item.answer for item in body.answers if item.exam_paper_item_id is not None}
    answer_by_order = {item.item_order: item.answer for item in body.answers if item.item_order is not None}
    now = utcnow()
    for item in exams_repo.list_items_by_paper(session, exam_paper_id):
        item.answer_content = answer_by_id.get(item.id) or answer_by_order.get(item.item_order) or ""
        item.answered_at = now
        item.updated_at = now
        session.add(item)
    paper.status = "submitted"
    paper.submitted_at = now
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return ok_response(_grade_exam(session, paper))
