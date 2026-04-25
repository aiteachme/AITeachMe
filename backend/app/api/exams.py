"""Exams API endpoints."""

from __future__ import annotations

import hashlib
import json
import re

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import ExamPaper, ExamPaperItem, QuestionTemplate, QuestionTypeRegistry, exam_mode_value
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
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    QuestionTemplateItemResponse,
    QuestionTypeRegistryItemResponse,
    ExamStudyGuideFocusUnit,
    ExamStudyGuideResponse,
    ExamSubmitRequest,
)
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.live_stream import (
    format_sse_event,
    publish_workflow_stream_event,
    subscribe_workflow_stream,
)
from app.utils.time import utcnow
from app.workflows.examine import (
    run_exam_grade_workflow,
    run_exam_study_guide_workflow,
    run_question_build_workflow,
)
from app.workflows.profile import schedule_reviews, update_mastery_from_exam
from app.workflows.support.subjects.learning_context import load_subject_llm_context

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])
logger = structlog.get_logger(__name__)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _exam_stream_channel(subject: str, paper_id: int) -> str:
    return f"exam:{subject}:{paper_id}"


def _publish_exam_event(subject: str, paper_id: int, event: str, data: dict[str, object]) -> None:
    publish_workflow_stream_event(_exam_stream_channel(subject, paper_id), event, data)


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


def _json_dict(raw: str | None) -> dict[str, object]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hash_stem(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()


def _raise_not_found(detail: str, error_code: str = "EXAM_NOT_FOUND") -> None:
    raise AITeachMeError(detail=detail, error_code=error_code, status_code=404)


def _clean_exam_text(value: str | None) -> str:
    text = str(value or "")
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _build_exam_title(paper: ExamPaper) -> str:
    return f"{paper.exam_mode} · {paper.created_at.strftime('%m/%d %H:%M')}"


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
    if limit <= 0:
        return deduped
    return deduped[: max(1, limit)]


def _mastery_by_unit_id(session: Session, *, user_id: str, subject: str) -> dict[int, float]:
    return {
        int(state.knowledge_unit_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }


def _question_type_for_order(*, exam_mode: str, difficulty: str, item_order: int) -> str:
    del exam_mode, difficulty
    cycle = ["single_choice", "fill_blank"]
    return cycle[(item_order - 1) % len(cycle)]


def _difficulty_for_order(*, requested_difficulty: str, item_order: int) -> str:
    normalized = str(requested_difficulty or "medium").strip().lower()
    if normalized in {"easy", "medium", "hard"}:
        return normalized
    if normalized == "mixed":
        cycle = ["easy", "medium", "hard"]
        return cycle[(item_order - 1) % len(cycle)]
    return "medium"


def _build_exam_selection_context(
    *,
    source: str,
    knowledge_unit_ids: list[int],
    focus_prompt: str | None,
    user_prompt: str | None,
    style_prompt: str | None,
    requested_difficulty: str,
    sample_file_uids: list[str],
    generation_status: str = "generating",
    error_message: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "source": source,
        "knowledge_unit_ids": knowledge_unit_ids,
        "focus_prompt": focus_prompt,
        "user_prompt": user_prompt,
        "style_prompt": style_prompt,
        "requested_difficulty": requested_difficulty,
        "sample_file_uids": sample_file_uids,
        "generation_status": generation_status,
    }
    if error_message:
        payload["error_message"] = error_message
    return json.dumps(payload, ensure_ascii=False)


def _set_exam_generation_status(
    session: Session,
    paper: ExamPaper,
    *,
    status: str,
    error_message: str | None = None,
) -> ExamPaper:
    context = _json_dict(paper.selection_context_json)
    context["generation_status"] = status
    if error_message:
        context["error_message"] = error_message
    else:
        context.pop("error_message", None)
    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
    paper.status = status
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _require_generated_questions_by_order(
    *,
    build_result,
    expected_orders: list[int],
) -> dict[int, dict[str, object]]:
    if build_result.failed:
        detail = str(build_result.error.detail if build_result.error is not None else "").strip()
        raise AITeachMeError(
            detail=detail or "Exam question generation failed.",
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    state = build_result.require_value()
    build_error = str(state.get("error") or "").strip()
    if build_error:
        raise AITeachMeError(
            detail=build_error,
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    generated_questions = state.get("generated_questions") or []
    generated_by_order: dict[int, dict[str, object]] = {}
    invalid_orders: list[object] = []
    for item in generated_questions:
        if not isinstance(item, dict):
            invalid_orders.append(item)
            continue
        try:
            item_order = int(item["item_order"])
        except (KeyError, TypeError, ValueError):
            invalid_orders.append(item.get("item_order"))
            continue
        generated_by_order[item_order] = item

    if invalid_orders:
        raise AITeachMeError(
            detail=f"Exam question generation returned invalid item_order values: {invalid_orders}",
            error_code="EXAM_QUESTION_BUILD_INVALID",
            status_code=502,
        )

    missing_orders = [order for order in expected_orders if order not in generated_by_order]
    if missing_orders:
        raise AITeachMeError(
            detail=f"Exam question generation returned incomplete results; missing item_order values: {missing_orders}",
            error_code="EXAM_QUESTION_BUILD_INCOMPLETE",
            status_code=502,
        )

    return generated_by_order


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
    knowledge_unit_refs: list[dict[str, object]] | None = None,
) -> QuestionTemplate:
    stem_hash = _hash_stem(stem)
    refs = knowledge_unit_refs or [{"knowledge_unit_id": unit.id, "coverage_weight": 1.0, "role": "primary"}]
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
        existing.knowledge_unit_refs_json = json.dumps(refs, ensure_ascii=False)
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
        knowledge_unit_refs_json=json.dumps(refs, ensure_ascii=False),
    )
    return exams_repo.create_question_template(session, template)


async def _run_exam_generation_background(
    *,
    subject: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    requested_difficulty: str,
    focus_prompt: str | None,
    user_prompt: str | None,
    style_prompt: str | None,
) -> None:
    _publish_exam_event(
        subject,
        paper_id,
        "snapshot",
        {"exam_paper_id": paper_id, "status": "generating", "stage": "question_build"},
    )
    try:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.subject != subject or paper.user_id != user_id:
                return
            subject_row = _ensure_subject(session, subject, user_id)
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.subject == subject,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            exam_units = [unit_by_id[unit_id] for unit_id in unit_ids if unit_id in unit_by_id]
            if not exam_units:
                raise AITeachMeError(
                    detail="No persisted KnowledgeUnits are available for exam generation.",
                    error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
                    status_code=409,
                )
            subject_context = load_subject_llm_context(session, subject=subject)

            mastery_by_unit_id = _mastery_by_unit_id(session, user_id=user_id, subject=subject)

        build_result = await run_question_build_workflow(
            subject=subject,
            subject_name=subject_row.name,
            subject_description=subject_row.description,
            subject_user_intent=subject_row.user_intent,
            exam_mode=exam_mode,
            units=exam_units,
            specs=None,
            question_count=question_count,
            requested_difficulty=requested_difficulty,
            mastery_by_unit_id=mastery_by_unit_id,
            subject_context=subject_context,
            focus_prompt=focus_prompt or "",
            user_prompt=user_prompt or "",
            style_prompt=style_prompt or "",
        )
        generated_by_order = _require_generated_questions_by_order(
            build_result=build_result,
            expected_orders=list(range(1, question_count + 1)),
        )

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.subject != subject or paper.user_id != user_id:
                return
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.subject == subject,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            items: list[ExamPaperItem] = []
            for order in range(1, question_count + 1):
                generated = generated_by_order[order]
                primary_unit_id = int(generated.get("knowledge_unit_id") or 0)
                unit = unit_by_id.get(primary_unit_id)
                if unit is None:
                    continue
                refs = [
                    ref
                    for ref in list(generated.get("knowledge_unit_refs") or [])
                    if isinstance(ref, dict) and int(ref.get("knowledge_unit_id", 0) or 0) in unit_by_id
                ] or [{"knowledge_unit_id": primary_unit_id, "coverage_weight": 1.0, "role": "primary"}]
                template = _upsert_generated_template(
                    session,
                    subject=subject,
                    unit=unit,
                    difficulty=str(generated["difficulty"]),
                    question_type=str(generated["question_type"]),
                    stem=str(generated["stem"]),
                    answer=str(generated["correct_answer"]),
                    explanation=str(generated["explanation"]),
                    options=list(generated.get("options") or []) or None,
                    knowledge_unit_refs=refs,
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
            paper.total_items = len(items)
            paper.total_score = float(len(items))
            _set_exam_generation_status(session, paper, status="ready")

        _publish_exam_event(
            subject,
            paper_id,
            "done",
            {"exam_paper_id": paper_id, "status": "ready", "num_questions": len(items)},
        )
    except Exception as exc:
        error_message = str(getattr(exc, "detail", None) or exc or "Exam question generation failed.")
        logger.exception(
            "exam_generation_background_failed",
            subject=subject,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            question_count=question_count,
            error_message=error_message,
        )
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                _set_exam_generation_status(session, paper, status="failed", error_message=error_message)
        _publish_exam_event(
            subject,
            paper_id,
            "done",
            {"exam_paper_id": paper_id, "status": "failed", "error_message": error_message},
        )


async def _spawn_exam_generation_after_response(
    request: Request,
    *,
    subject: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    requested_difficulty: str,
    focus_prompt: str | None,
    user_prompt: str | None,
    style_prompt: str | None,
) -> None:
    request.app.state.background_task_registry.spawn(
        _run_exam_generation_background(
            subject=subject,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            unit_ids=unit_ids,
            question_count=question_count,
            requested_difficulty=requested_difficulty,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            style_prompt=style_prompt,
        ),
        kind="exam.generate",
        subject=subject,
        name=f"exam.generate:{subject}:{paper_id}",
    )


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
        explanation=item.feedback_text or item.explanation_snapshot,
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


def _question_template_response(template: QuestionTemplate) -> QuestionTemplateItemResponse:
    options_payload = None
    if template.options_json:
        try:
            decoded_options = json.loads(template.options_json)
            if isinstance(decoded_options, list):
                options_payload = [str(item) for item in decoded_options]
        except json.JSONDecodeError:
            options_payload = None

    return QuestionTemplateItemResponse(
        id=template.id or 0,
        subject=template.subject,
        knowledge_unit_id=template.knowledge_unit_id,
        question_type=template.question_type,
        difficulty=template.difficulty,
        stem=template.stem,
        options=options_payload,
        answer=template.answer,
        explanation=template.explanation,
        knowledge_unit_refs=_json_list(template.knowledge_unit_refs_json),
        selection_hints=_json_dict(template.selection_hints_json),
        template_version=template.template_version,
        status=template.status,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _question_type_response(item: QuestionTypeRegistry) -> QuestionTypeRegistryItemResponse:
    return QuestionTypeRegistryItemResponse(
        id=item.id or 0,
        type_key=item.type_key,
        display_name=item.display_name,
        scope=item.scope,
        subject=item.subject,
        description=item.description,
        answer_format=item.answer_format,
        grading_method=item.grading_method,
        option_schema=_json_dict(item.option_schema_json),
        rubric=_json_dict(item.rubric_json),
        source=item.source,
        confidence=item.confidence,
        is_system=item.is_system,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
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


async def _study_guide_detail(session: Session, paper: ExamPaper) -> ExamStudyGuideResponse:
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

    weak_states = profile_repo.list_weak_knowledge_states(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        target_kind="knowledge_unit",
    )
    pending_reviews = profile_repo.list_pending_reviews(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
    )
    wrong_question_summaries = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=paper.user_id,
        subject=paper.subject,
        knowledge_unit_ids=[
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        ],
        limit=5,
    )

    score_summary = (
        f"得分 {paper.score_obtained or 0:.1f}/{paper.total_score or 0:.1f}，"
        f"共 {paper.total_items} 题，"
        f"正确 {sum(1 for item in items if item.is_correct)} 题，"
        f"错误或未作答 {sum(1 for item in items if item.is_correct is not True)} 题。"
    )
    weak_point_payload = [
        {
            "knowledge_unit_id": int(state.knowledge_unit_id) if state.knowledge_unit_id is not None else None,
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "mastery_score": round(float(state.mastery_score), 3),
            "reason": (
                f"掌握度 {float(state.mastery_score):.0%}，"
                f"累计 {state.total_attempts} 次练习，"
                f"正确 {state.correct_attempts} 次。"
            ),
        }
        for state in weak_states[:5]
    ]
    review_payload = [
        {
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "reason": state.review_reason or "建议尽快回顾",
            "priority": round(float(state.review_priority), 3),
        }
        for state in pending_reviews[:5]
    ]

    response = await run_exam_study_guide_workflow(
        exam_paper_id=paper.id or 0,
        subject=paper.subject,
        exam_title=_build_exam_title(paper),
        score_summary=score_summary,
        wrong_question_summaries=wrong_question_summaries,
        weak_points=weak_point_payload,
        pending_reviews=review_payload,
        generated_at=utcnow(),
    )
    if response.focus_units:
        normalized_focus_units: list[ExamStudyGuideFocusUnit] = []
        for item in response.focus_units:
            if item.knowledge_unit_name.strip():
                normalized_focus_units.append(item)
        response.focus_units = normalized_focus_units
    return response


async def _grade_exam(session: Session, paper: ExamPaper) -> ExamGradeResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    decisions = await run_exam_grade_workflow(subject=paper.subject, items=items)
    total_score = 0.0
    score_obtained = 0.0
    now = utcnow()
    for item, decision in zip(items, decisions, strict=False):
        item.is_correct = decision.is_correct
        item.score_max = decision.score_max
        item.score_obtained = decision.score_obtained
        item.error_cause_label = decision.error_cause_label
        item.feedback_text = decision.feedback_text
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
    request: Request,
    background_tasks: BackgroundTasks,
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
        limit=0,
    )
    if not units:
        raise AITeachMeError(
            detail="No active KnowledgeUnits are available for exam generation.",
            error_code="NO_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )
    exam_units = [unit for unit in units if unit.id is not None]
    if not exam_units:
        raise AITeachMeError(
            detail="No persisted KnowledgeUnits are available for exam generation.",
            error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )

    mode = exam_mode_value(body.exam_mode)
    requested_difficulty = body.difficulty or "medium"
    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            status="generating",
            total_items=question_count,
            total_score=float(question_count),
            selection_context_json=_build_exam_selection_context(
                source="knowledge_unit_llm",
                knowledge_unit_ids=[int(unit.id or 0) for unit in exam_units],
                focus_prompt=body.focus_prompt,
                user_prompt=body.user_prompt,
                style_prompt=body.style_prompt,
                requested_difficulty=requested_difficulty,
                sample_file_uids=body.sample_file_uids or [],
            ),
        ),
    )
    paper_id = paper.id or 0
    background_tasks.add_task(
        _spawn_exam_generation_after_response,
        request,
        subject=normalized,
        user_id=user.user_id,
        paper_id=paper_id,
        exam_mode=mode,
        unit_ids=[int(unit.id or 0) for unit in exam_units],
        question_count=question_count,
        requested_difficulty=requested_difficulty,
        focus_prompt=body.focus_prompt,
        user_prompt=body.user_prompt,
        style_prompt=body.style_prompt,
    )
    return ok_response(
        ExamGenerateResponse(
            id=paper_id,
            status=paper.status,
            error_message=None,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
            subject=paper.subject,
            user_id=paper.user_id,
            exam_mode=paper.exam_mode,
            num_questions=question_count,
            exam_paper_id=paper_id,
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
    "/question-templates",
    response_model=ApiResponse[list[QuestionTemplateItemResponse]],
    summary="List question templates for the subject",
    responses=build_error_responses([400, 404, 500]),
)
async def question_templates(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTemplateItemResponse]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTemplate)
            .where(QuestionTemplate.subject == normalized)
            .order_by(QuestionTemplate.created_at.desc(), QuestionTemplate.id.desc())
        ).all()
    )
    return ok_response([_question_template_response(item) for item in rows])


@router.get(
    "/question-types",
    response_model=ApiResponse[list[QuestionTypeRegistryItemResponse]],
    summary="List global and subject question types",
    responses=build_error_responses([400, 404, 500]),
)
async def question_types(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTypeRegistryItemResponse]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTypeRegistry)
            .where(
                QuestionTypeRegistry.is_active == True,  # noqa: E712
                or_(
                    QuestionTypeRegistry.scope == "global",
                    QuestionTypeRegistry.subject == normalized,
                ),
            )
            .order_by(
                QuestionTypeRegistry.scope.asc(),
                QuestionTypeRegistry.subject.asc(),
                QuestionTypeRegistry.type_key.asc(),
            )
        ).all()
    )
    return ok_response([_question_type_response(item) for item in rows])


@router.get(
    "/{exam_paper_id}/stream",
    summary="SSE stream for exam generation status",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_generation_stream(
    request: Request,
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    async def event_generator():
        def snapshot_payload() -> dict[str, object]:
            with managed_session() as stream_session:
                current = exams_repo.get_exam_paper_by_id(stream_session, exam_paper_id)
                if current is None:
                    return {
                        "exam_paper_id": exam_paper_id,
                        "status": "failed",
                        "error_message": "Exam paper no longer exists.",
                    }
                context = _json_dict(current.selection_context_json)
                return {
                    "exam_paper_id": exam_paper_id,
                    "status": current.status,
                    "num_questions": current.total_items,
                    "error_message": context.get("error_message"),
                    "updated_at": current.updated_at,
                }

        initial = snapshot_payload()
        yield format_sse_event("snapshot", initial)
        if str(initial.get("status") or "") in {"ready", "failed", "graded", "submitted"}:
            yield format_sse_event("done", initial)
            return

        with subscribe_workflow_stream(_exam_stream_channel(normalized, exam_paper_id)) as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await queue.get()
                except Exception:
                    break
                yield format_sse_event(event.event, event.data)
                if event.event == "done":
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
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


@router.delete(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="Delete exam paper",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_exam_paper(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDeleteResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    exams_repo.delete_exam_paper_cascade(session, paper_id=exam_paper_id)
    return ok_response(ExamPaperDeleteResponse(deleted=True, exam_paper_id=exam_paper_id))


@router.get(
    "/{exam_paper_id}/study-guide",
    response_model=ApiResponse[ExamStudyGuideResponse],
    summary="Generate study guide from a graded exam",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def exam_study_guide(
    subject: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamStudyGuideResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != normalized or paper.user_id != user.user_id:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status != "graded":
        raise AITeachMeError(
            detail="Study guide is available only after grading is complete.",
            error_code="EXAM_NOT_GRADED",
            status_code=409,
        )
    return ok_response(await _study_guide_detail(session, paper))


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
    if paper.status == "generating":
        raise AITeachMeError(detail="Exam is still generating.", error_code="EXAM_STILL_GENERATING", status_code=409)
    if paper.status == "failed":
        raise AITeachMeError(detail="Exam generation failed.", error_code="EXAM_GENERATION_FAILED", status_code=409)
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
    return ok_response(await _grade_exam(session, paper))
