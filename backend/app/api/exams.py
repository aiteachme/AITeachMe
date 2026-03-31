"""Exam API endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import KnowledgeNode
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, PaginatedData, build_paginated_data, ok_response
from app.schemas.exams import (
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamGradeResponse,
    ExamHistoryItem,
    ExamNodeLinkResponse,
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    ExamSubmitRequest,
    QuestionBankItemResponse,
)
from app.services.exams_service import (
    ExamGenerationResult,
    ExamGradingResult,
    ExamPaperDetail,
    QuestionBankItem,
    delete_exam_paper,
    get_exam_history,
    get_exam_paper_detail,
    get_question_bank,
    submit_exam_answers,
    trigger_exam_generate,
    trigger_exam_grade,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])


def _parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _to_exam_generate_response(job: ExamGenerationResult) -> ExamGenerateResponse:
    return ExamGenerateResponse(
        id=job.id or 0,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        subject=job.subject,
        user_id=job.user_id,
        exam_mode=job.exam_mode,
        num_questions=job.num_questions,
        exam_paper_id=job.exam_paper_id,
        theme_tree_node_id=job.theme_tree_node_id,
        teaching_unit_ids=[int(item) for item in _parse_json_list(job.teaching_unit_ids_json)],
        sample_file_uids=[str(item) for item in _parse_json_list(job.sample_file_uids_json)],
    )


def _to_exam_grade_response(job: ExamGradingResult) -> ExamGradeResponse:
    return ExamGradeResponse(
        id=job.id or 0,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        exam_paper_id=job.exam_paper_id,
        score=job.score,
        states_updated=job.states_updated,
        tasks_created=job.tasks_created,
        mastery_consumed=job.mastery_consumed,
    )


def _to_exam_history_item(paper) -> ExamHistoryItem:
    return ExamHistoryItem(
        id=paper.id or 0,
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


def _build_node_link_responses(
    session: Session,
    *,
    subject: str,
    user_id: str,
    raw_links: list[Any],
) -> list[ExamNodeLinkResponse]:
    node_cache: dict[int, str] = {}
    mastery_cache: dict[int, float | None] = {}
    responses: list[ExamNodeLinkResponse] = []

    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        raw_node_id = raw_link.get("knowledge_node_id")
        if isinstance(raw_node_id, int):
            node_id = raw_node_id
        elif isinstance(raw_node_id, str) and raw_node_id.isdigit():
            node_id = int(raw_node_id)
        else:
            continue

        if node_id not in node_cache:
            node = session.get(KnowledgeNode, node_id)
            node_cache[node_id] = node.canonical_name if node is not None else f"Node {node_id}"
        if node_id not in mastery_cache:
            state = profile_repo.get_knowledge_state(
                session,
                user_id=user_id,
                subject=subject,
                knowledge_node_id=node_id,
            )
            mastery_cache[node_id] = state.mastery_score if state is not None else None

        coverage_weight = raw_link.get("coverage_weight", 0.0)
        try:
            normalized_weight = float(coverage_weight)
        except (TypeError, ValueError):
            normalized_weight = 0.0

        responses.append(
            ExamNodeLinkResponse(
                knowledge_node_id=node_id,
                knowledge_node_name=node_cache[node_id],
                coverage_weight=normalized_weight,
                role=str(raw_link.get("role", "primary")),
                mastery_score=mastery_cache[node_id],
            )
        )
    return responses


def _to_exam_paper_detail_response(session: Session, detail: ExamPaperDetail) -> ExamPaperDetailResponse:
    paper = detail.paper
    selection_context = _parse_json_object(paper.selection_context_json)
    reveal_correct_answer = paper.status == "graded"
    items: list[ExamPaperItemResponse] = []

    for item in detail.items:
        options = _parse_json_list(item.options_snapshot_json)
        attempts = detail.attempts_by_item_id.get(item.id or -1)
        raw_links = _parse_json_list(item.node_refs_json)
        node_links = _build_node_link_responses(
            session,
            subject=paper.subject,
            user_id=paper.user_id,
            raw_links=raw_links,
        )
        items.append(
            ExamPaperItemResponse(
                id=item.id or 0,
                item_order=item.item_order,
                question_template_id=item.question_template_id,
                question_type=item.question_type,
                difficulty=item.difficulty,
                stem=item.stem_snapshot,
                options=[str(option) for option in options] if options else None,
                correct_answer=item.answer_snapshot if reveal_correct_answer else None,
                explanation=item.explanation_snapshot,
                teaching_unit_id=item.teaching_unit_id,
                node_links=node_links,
                user_answer=(attempts.answer_content if attempts is not None else None),
                is_correct=(attempts.is_correct if attempts is not None else None),
                score_obtained=(attempts.score_obtained if attempts is not None else None),
                score_max=(attempts.score_max if attempts is not None else None),
                error_cause_label=(attempts.error_cause_label if attempts is not None else None),
            )
        )

    return ExamPaperDetailResponse(
        id=paper.id or 0,
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
        selection_context=selection_context,
        items=items,
    )


def _to_question_bank_item_response(item: QuestionBankItem) -> QuestionBankItemResponse:
    return QuestionBankItemResponse(
        question_template_id=item.question_template_id,
        stem=item.stem,
        question_type=item.question_type,
        difficulty=item.difficulty,
        teaching_unit_id=item.teaching_unit_id,
        times_asked=item.times_asked,
        last_asked_at=item.last_asked_at,
        last_exam_paper_id=item.last_exam_paper_id,
        knowledge_points=item.knowledge_points,
        style_summary=item.style_summary,
    )


@router.post(
    "/generate",
    response_model=ApiResponse[ExamGenerateResponse],
    summary="Trigger exam generation",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_generate(
    subject: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await trigger_exam_generate(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_mode=body.exam_mode,
        num_questions=body.num_questions,
        user_prompt=body.user_prompt,
        style_prompt=body.style_prompt,
        focus_prompt=body.focus_prompt,
        sample_file_uids=body.sample_file_uids,
        theme_tree_node_id=body.theme_tree_node_id,
        teaching_unit_ids=body.teaching_unit_ids,
    )
    return ok_response(_to_exam_generate_response(job))


@router.post(
    "/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="Paginated exam history",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_exam_history(
    subject: str = Path(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    history = await get_exam_history(
        session,
        subject=normalized,
        user_id=user.user_id,
        page=page,
        size=size,
    )
    return ok_response(
        build_paginated_data(
            items=[_to_exam_history_item(item) for item in history.items],
            page=history.page,
            size=history.size,
            total=history.total,
        )
    )


@router.post(
    "/question-bank",
    response_model=ApiResponse[list[QuestionBankItemResponse]],
    summary="Question bank view",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_question_bank(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionBankItemResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    items = await get_question_bank(session, subject=normalized, user_id=user.user_id)
    return ok_response([_to_question_bank_item_response(item) for item in items])


@router.post(
    "/{exam_paper_id:int}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Exam paper detail",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_exam_detail(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    detail = await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(_to_exam_paper_detail_response(session, detail))


@router.post(
    "/{exam_paper_id:int}/delete",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="Delete exam paper",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_delete_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDeleteResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    await delete_exam_paper(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(ExamPaperDeleteResponse(deleted=True, exam_paper_id=exam_paper_id))


@router.post(
    "/{exam_paper_id:int}/submit",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Submit exam answers",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_submit_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    body: ExamSubmitRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)

    answers: dict[int | str, str] = {}
    for answer in body.answers:
        if answer.exam_paper_item_id is not None:
            answers[answer.exam_paper_item_id] = answer.answer
        elif answer.item_order is not None:
            answers[answer.item_order] = answer.answer

    await submit_exam_answers(
        session,
        subject=normalized,
        exam_paper_id=exam_paper_id,
        user_id=user.user_id,
        answers=answers,
    )
    detail = await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(_to_exam_paper_detail_response(session, detail))


@router.post(
    "/{exam_paper_id:int}/grade",
    response_model=ApiResponse[ExamGradeResponse],
    summary="Trigger exam grading",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_grade(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    regrade: bool = Query(False),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    job = await trigger_exam_grade(
        session,
        exam_paper_id=exam_paper_id,
        regrade=regrade,
    )
    return ok_response(_to_exam_grade_response(job))
