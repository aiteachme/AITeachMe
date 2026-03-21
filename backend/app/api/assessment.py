"""Assessment 接口。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.assessment import (
    ExamGenerateJobStatusResponse,
    ExamGenerateRequest,
    ExamGradeJobStatusResponse,
    ExamHistoryItem,
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    ExamSubmitRequest,
    MasteryOverviewResponse,
    MasteryStateResponse,
    QuestionBankItemResponse,
    ReviewTaskResponse,
)
from app.schemas.common import ApiResponse, PaginatedData, build_paginated_data, ok_response
from app.services.assessment_service import (
    ExamPaperDetail,
    MasteryOverview,
    QuestionBankItem,
    complete_review_task,
    delete_exam_paper,
    get_exam_generate_job_status,
    get_exam_grade_job_status,
    get_exam_history,
    get_exam_paper_detail,
    get_mastery_detail,
    get_mastery_overview,
    get_question_bank,
    get_review_tasks,
    submit_exam_answers,
    trigger_exam_generate,
    trigger_exam_grade,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects", tags=["assessment"])


def _parse_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _to_exam_generate_job_response(job) -> ExamGenerateJobStatusResponse:
    return ExamGenerateJobStatusResponse(
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
    )


def _to_exam_grade_job_response(job) -> ExamGradeJobStatusResponse:
    return ExamGradeJobStatusResponse(
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


def _to_exam_paper_detail_response(detail: ExamPaperDetail) -> ExamPaperDetailResponse:
    paper = detail.paper
    items: list[ExamPaperItemResponse] = []
    for item in detail.items:
        options = _parse_json_list(item.snapshot_options)
        attempts = detail.attempts_by_item_id.get(item.id or -1)
        items.append(
            ExamPaperItemResponse(
                id=item.id or 0,
                item_order=item.item_order,
                question_template_id=item.question_template_id,
                question_type=item.snapshot_question_type,
                difficulty=item.snapshot_difficulty,
                stem=item.snapshot_stem,
                options=[str(option) for option in options] if options else None,
                explanation=item.snapshot_explanation,
                teaching_unit_id=item.snapshot_teaching_unit_id,
                node_links=_parse_json_list(item.snapshot_node_links_json),
                user_answer=(attempts.user_answer if attempts is not None else None),
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
        items=items,
    )


def _to_mastery_state_response(state) -> MasteryStateResponse:
    return MasteryStateResponse(
        id=state.id or 0,
        granularity=state.granularity,
        target_id=state.target_id,
        mastery_score=state.mastery_score,
        confidence_score=state.confidence_score,
        stability_score=state.stability_score,
        forgetting_due_at=state.forgetting_due_at,
        review_priority=state.review_priority,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        last_attempt_at=state.last_attempt_at,
        state_version=state.state_version,
        updated_at=state.updated_at,
    )


def _to_mastery_overview_response(overview: MasteryOverview) -> MasteryOverviewResponse:
    return MasteryOverviewResponse(
        subject=overview.subject,
        user_id=overview.user_id,
        weak_unit_count=overview.weak_unit_count,
        weak_node_count=overview.weak_node_count,
        unit_states=[_to_mastery_state_response(item) for item in overview.unit_states],
        node_states=[_to_mastery_state_response(item) for item in overview.node_states],
    )


def _to_review_task_response(task) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        id=task.id or 0,
        user_id=task.user_id,
        subject=task.subject,
        task_type=task.task_type,
        target_id=task.target_id,
        target_granularity=task.target_granularity,
        priority=task.priority,
        scheduled_at=task.scheduled_at,
        status=task.status,
        interval_days=task.interval_days,
        ease_factor=task.ease_factor,
        repetition_count=task.repetition_count,
        reason=task.reason,
        source_state_id=task.source_state_id,
        source_exam_paper_id=task.source_exam_paper_id,
        created_at=task.created_at,
        completed_at=task.completed_at,
        expired_at=task.expired_at,
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
    )


@router.post(
    "/{subject}/exam/generate",
    response_model=ApiResponse[ExamGenerateJobStatusResponse],
    summary="触发试卷生成",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_generate(
    subject: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await trigger_exam_generate(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_mode=body.exam_mode,
        num_questions=body.num_questions,
        user_prompt=body.user_prompt,
        theme_tree_node_id=body.theme_tree_node_id,
        teaching_unit_ids=body.teaching_unit_ids,
    )
    return ok_response(_to_exam_generate_job_response(job))


@router.get(
    "/{subject}/exam/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="分页考试历史",
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


@router.get(
    "/{subject}/exam/generate-jobs/{job_id:int}",
    response_model=ApiResponse[ExamGenerateJobStatusResponse],
    summary="组卷任务状态",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_generate_job_status(
    subject: str = Path(...),
    job_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await get_exam_generate_job_status(
        session,
        subject=normalized,
        job_id=job_id,
        user_id=user.user_id,
    )
    return ok_response(_to_exam_generate_job_response(job))


@router.get(
    "/{subject}/exam/grade-jobs/{job_id:int}",
    response_model=ApiResponse[ExamGradeJobStatusResponse],
    summary="判卷任务状态",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_grade_job_status(
    subject: str = Path(...),
    job_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await get_exam_grade_job_status(
        session,
        subject=normalized,
        job_id=job_id,
        user_id=user.user_id,
    )
    return ok_response(_to_exam_grade_job_response(job))


@router.get(
    "/{subject}/exam/question-bank",
    response_model=ApiResponse[list[QuestionBankItemResponse]],
    summary="题库视图（列出出过的题目）",
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


@router.get(
    "/{subject}/exam/{exam_paper_id:int}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="试卷详情",
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
    return ok_response(_to_exam_paper_detail_response(detail))


@router.delete(
    "/{subject}/exam/{exam_paper_id:int}",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="删除试卷",
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
    "/{subject}/exam/{exam_paper_id:int}/submit",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="提交答案",
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
    return ok_response(_to_exam_paper_detail_response(detail))


@router.post(
    "/{subject}/exam/{exam_paper_id:int}/grade",
    response_model=ApiResponse[ExamGradeJobStatusResponse],
    summary="触发判分",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_grade(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    regrade: bool = Query(False),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeJobStatusResponse]:
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
    return ok_response(_to_exam_grade_job_response(job))


@router.get(
    "/{subject}/mastery",
    response_model=ApiResponse[MasteryOverviewResponse],
    summary="掌握度概览",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_mastery_overview(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryOverviewResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    overview = await get_mastery_overview(session, subject=normalized, user_id=user.user_id)
    return ok_response(_to_mastery_overview_response(overview))


@router.get(
    "/{subject}/mastery/unit/{target_id:int}",
    response_model=ApiResponse[MasteryStateResponse],
    summary="单元掌握度详情",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_unit_mastery_detail(
    subject: str = Path(...),
    target_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryStateResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    state = await get_mastery_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        target_id=target_id,
        granularity="unit",
    )
    return ok_response(_to_mastery_state_response(state))


@router.get(
    "/{subject}/mastery/node/{target_id:int}",
    response_model=ApiResponse[MasteryStateResponse],
    summary="节点掌握度详情",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_node_mastery_detail(
    subject: str = Path(...),
    target_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryStateResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    state = await get_mastery_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        target_id=target_id,
        granularity="node",
    )
    return ok_response(_to_mastery_state_response(state))


@router.get(
    "/{subject}/review/tasks",
    response_model=ApiResponse[list[ReviewTaskResponse]],
    summary="待处理复习任务",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_review_tasks(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[ReviewTaskResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    tasks = await get_review_tasks(session, subject=normalized, user_id=user.user_id)
    return ok_response([_to_review_task_response(item) for item in tasks])


@router.post(
    "/{subject}/review/tasks/{task_id:int}/complete",
    response_model=ApiResponse[ReviewTaskResponse],
    summary="完成复习任务",
    responses=build_error_responses([400, 404, 500]),
)
async def api_complete_review_task(
    subject: str = Path(...),
    task_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ReviewTaskResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    task = await complete_review_task(
        session,
        subject=normalized,
        task_id=task_id,
        user_id=user.user_id,
    )
    return ok_response(_to_review_task_response(task))
