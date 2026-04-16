"""Exams API endpoints."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import ExamPaper, ExamPaperItem, QuestionTemplate, exam_mode_value
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.repositories import exams_repo
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
from app.workflows.profile.mastery_updater import update_mastery_from_exam
from app.workflows.profile.review_scheduler import schedule_reviews

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])


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


def _pick_knowledge_units(
    session: Session,
    *,
    subject: str,
    focus_prompt: str | None,
    limit: int,
) -> list[KnowledgeUnit]:
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.status == "active",
    )
    units = list(session.exec(stmt.order_by(KnowledgeUnit.id)).all())
    focus = (focus_prompt or "").strip().casefold()
    if focus:
        focused = [
            unit
            for unit in units
            if focus in unit.canonical_name.casefold()
            or focus in unit.summary.casefold()
            or focus in unit.knowledge_unit_type.casefold()
        ]
        if focused:
            units = focused
    return units[: max(1, limit)]


def _template_for_unit(
    session: Session,
    *,
    subject: str,
    unit: KnowledgeUnit,
    difficulty: str,
) -> QuestionTemplate:
    stem = f"Explain the key idea of {unit.canonical_name}."
    answer = unit.summary.strip() or unit.canonical_name
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
        return existing
    template = QuestionTemplate(
        subject=subject,
        teaching_unit_id=None,
        knowledge_unit_id=unit.id,
        question_type="short_answer",
        difficulty=difficulty,
        stem=stem,
        stem_hash=stem_hash,
        answer=answer,
        explanation=f"Review the definition and usage of {unit.canonical_name}.",
        knowledge_unit_refs_json=json.dumps(
            [{"knowledge_unit_id": unit.id, "coverage_weight": 1.0, "role": "primary"}],
            ensure_ascii=False,
        ),
    )
    return exams_repo.create_question_template(session, template)


def _paper_item_response(item: ExamPaperItem) -> ExamPaperItemResponse:
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
        teaching_unit_id=item.teaching_unit_id or 0,
        knowledge_unit_links=[
            {
                "knowledge_unit_id": int(ref.get("knowledge_unit_id", 0) or 0),
                "knowledge_unit_name": "",
                "coverage_weight": float(ref.get("coverage_weight", 1.0) or 1.0),
                "role": str(ref.get("role", "primary")),
                "mastery_score": None,
            }
            for ref in _json_list(item.knowledge_unit_refs_json)
        ],
        user_answer=item.answer_content or None,
        is_correct=item.is_correct,
        score_obtained=item.score_obtained,
        score_max=item.score_max,
        error_cause_label=item.error_cause_label,
    )


def _paper_detail(session: Session, paper: ExamPaper) -> ExamPaperDetailResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
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
        items=[_paper_item_response(item) for item in items],
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
        subject=normalized,
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
    difficulty = body.difficulty or "medium"
    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            status="ready",
            total_items=len(units),
            total_score=float(len(units)),
            teaching_unit_ids_json=json.dumps([], ensure_ascii=False),
            selection_context_json=json.dumps(
                {
                    "source": "knowledge_unit",
                    "knowledge_unit_ids": [unit.id for unit in units],
                    "focus_prompt": body.focus_prompt,
                },
                ensure_ascii=False,
            ),
        ),
    )
    items: list[ExamPaperItem] = []
    for order, unit in enumerate(units, start=1):
        template = _template_for_unit(session, subject=normalized, unit=unit, difficulty=difficulty)
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
                teaching_unit_id=None,
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
            theme_tree_node_id=body.theme_tree_node_id,
            teaching_unit_ids=body.teaching_unit_ids or [],
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
