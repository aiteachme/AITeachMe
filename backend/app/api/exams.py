"""Exam API endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models import KnowledgeNode, UserKnowledgeState
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


def _collect_node_ids(raw_links: list[Any]) -> list[int]:
    node_ids: list[int] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        raw_node_id = raw_link.get("knowledge_node_id")
        if isinstance(raw_node_id, int) and raw_node_id > 0:
            node_ids.append(raw_node_id)
            continue
        if isinstance(raw_node_id, str) and raw_node_id.isdigit():
            node_ids.append(int(raw_node_id))
    return list(dict.fromkeys(node_ids))


def _build_node_name_map(
    session: Session,
    *,
    node_ids: list[int],
) -> dict[int, str]:
    if not node_ids:
        return {}

    rows = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))).all())
    return {
        int(node.id): node.canonical_name
        for node in rows
        if node.id is not None
    }


def _build_node_mastery_map(
    session: Session,
    *,
    subject: str,
    user_id: str,
    node_ids: list[int],
) -> dict[int, float | None]:
    if not node_ids:
        return {}

    rows = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.subject == subject,
                UserKnowledgeState.knowledge_node_id.in_(node_ids),
                UserKnowledgeState.teaching_unit_id.is_(None),
            )
        ).all()
    )
    return {
        int(state.knowledge_node_id): state.mastery_score
        for state in rows
        if state.knowledge_node_id is not None
    }


def _build_node_link_responses(
    *,
    raw_links: list[Any],
    node_name_by_id: dict[int, str],
    mastery_by_node_id: dict[int, float | None],
) -> list[ExamNodeLinkResponse]:
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

        coverage_weight = raw_link.get("coverage_weight", 0.0)
        try:
            normalized_weight = float(coverage_weight)
        except (TypeError, ValueError):
            normalized_weight = 0.0

        responses.append(
            ExamNodeLinkResponse(
                knowledge_node_id=node_id,
                knowledge_node_name=node_name_by_id.get(node_id, f"Node {node_id}"),
                coverage_weight=normalized_weight,
                role=str(raw_link.get("role", "primary")),
                mastery_score=mastery_by_node_id.get(node_id),
            )
        )
    return responses


def _to_exam_paper_detail_response(session: Session, detail: ExamPaperDetail) -> ExamPaperDetailResponse:
    paper = detail.paper
    selection_context = _parse_json_object(paper.selection_context_json)
    reveal_correct_answer = paper.status == "graded"
    item_links = {
        item.id or 0: _parse_json_list(item.node_refs_json)
        for item in detail.items
    }
    linked_node_ids = list(
        dict.fromkeys(
            node_id
            for raw_links in item_links.values()
            for node_id in _collect_node_ids(raw_links)
        )
    )
    node_name_by_id = _build_node_name_map(session, node_ids=linked_node_ids)
    mastery_by_node_id = _build_node_mastery_map(
        session,
        subject=paper.subject,
        user_id=paper.user_id,
        node_ids=linked_node_ids,
    )
    items: list[ExamPaperItemResponse] = []

    for item in detail.items:
        options = _parse_json_list(item.options_snapshot_json)
        attempts = detail.attempts_by_item_id.get(item.id or -1)
        node_links = _build_node_link_responses(
            raw_links=item_links.get(item.id or 0, []),
            node_name_by_id=node_name_by_id,
            mastery_by_node_id=mastery_by_node_id,
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    job = await trigger_exam_generate(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_mode=body.exam_mode,
        difficulty=body.difficulty,
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    get_subject_record(session, normalized, owner_user_id=user.user_id)

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
    get_subject_record(session, normalized, owner_user_id=user.user_id)

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
