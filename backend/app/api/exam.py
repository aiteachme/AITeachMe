"""Exam generation, submission, and history routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.docs import build_error_responses
from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.exam import (
    AnswerResultItem,
    ExamGenerateRequest,
    ExamHistoryResponse,
    ExamResponse,
    SubmitRequest,
    SubmitResponse,
)
from app.services.exam_service import create_exam, submit_exam
from app.services.presenters import (
    to_answer_result_item,
    to_exam_history_response,
    to_exam_response,
    to_submit_response,
)

router = APIRouter(prefix="/api/v1", tags=["exam"])


@router.post(
    "/subjects/{subject}/exam/generate",
    response_model=ExamResponse,
    summary="生成测验",
    description="根据学科、知识点范围和难度分布要求生成一份新考卷。",
    response_description="新生成的考卷信息。",
    responses=build_error_responses([400, 500, 502, 503]),
)
async def generate_exam(
    body: ExamGenerateRequest = Body(..., description="考卷生成请求体。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ExamResponse:
    """Generate a new exam while preserving the existing public response shape."""
    exam, questions = await create_exam(
        session,
        subject=subject,
        num_questions=body.num_questions,
        difficulty_distribution=body.difficulty_distribution,
        knowledge_points=body.knowledge_points,
    )
    return to_exam_response(exam.id, questions)


@router.post(
    "/exam/{exam_id}/submit",
    response_model=SubmitResponse,
    summary="提交答卷",
    description="根据 exam_id 提交用户答案并返回总分、逐题判分结果及错因分析。",
    response_description="判分结果摘要。",
    responses=build_error_responses([404, 500, 502, 503]),
)
async def submit_answers(
    body: SubmitRequest = Body(..., description="答卷提交请求体。"),
    exam_id: int = Path(..., description="待提交考卷的 ID。", examples=[5]),
    session: Session = Depends(get_db),
) -> SubmitResponse:
    """Submit answers for one exam and return grading results."""
    answers_dict = {a.question_key: a.answer for a in body.answers}
    submission, records, mistakes, questions = await submit_exam(
        session, exam_id=exam_id, answers=answers_dict
    )

    # 构建 question_key → Question 映射
    q_map = {q.question_key: q for q in questions}
    # 构建 answer_record_id → Mistake 映射
    m_map = {m.answer_record_id: m for m in mistakes}

    results: list[AnswerResultItem] = []
    for r in records:
        q = q_map.get(next((qq.question_key for qq in questions if qq.id == r.question_id), ""))
        mistake = m_map.get(r.id)
        results.append(
            to_answer_result_item(
                question_key=q.question_key if q else "",
                is_correct=r.is_correct,
                user_answer=r.user_answer,
                correct_answer=q.answer if q else "",
                explanation=q.explanation if q else "",
                analysis=mistake.analysis if mistake else None,
            )
        )

    return to_submit_response(submission.id, submission.score, results)


@router.post(
    "/subjects/{subject}/exam/history",
    response_model=ExamHistoryResponse,
    summary="获取考试历史",
    description="分页返回指定学科下的历史考卷与最近提交信息。",
    response_description="考试历史分页列表。",
    responses=build_error_responses([400, 500]),
)
async def get_exam_history(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ExamHistoryResponse:
    """Return paginated exam history for one subject."""
    from app.repositories.exam_repo import list_exam_history_by_subject

    items, total = list_exam_history_by_subject(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_exam_history_response(items, total)
