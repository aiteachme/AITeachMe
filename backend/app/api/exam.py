"""
考试端点

POST /api/v1/subjects/{subject}/exam/generate — 生成考卷
POST /api/v1/exam/{exam_id}/submit — 提交答卷
GET  /api/v1/subjects/{subject}/exam/history — 考试历史

需求：9.1, 9.5, 10.1, 10.5, 10.6
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.exam import (
    ExamGenerateRequest,
    ExamResponse,
    QuestionItem,
    SubmitRequest,
    SubmitResponse,
    AnswerResultItem,
    ExamHistoryItem,
    ExamHistoryResponse,
)
from app.services.exam_service import create_exam, submit_exam

router = APIRouter(prefix="/api/v1", tags=["exam"])


@router.post("/subjects/{subject}/exam/generate", response_model=ExamResponse)
async def generate_exam(
    body: ExamGenerateRequest,
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ExamResponse:
    """AI 生成考卷。响应中不暴露 answer 字段。"""
    exam, questions = await create_exam(
        session,
        subject=subject,
        num_questions=body.num_questions,
        difficulty_distribution=body.difficulty_distribution,
        knowledge_points=body.knowledge_points,
    )
    return ExamResponse(
        exam_id=exam.id,  # type: ignore[arg-type]
        questions=[
            QuestionItem(
                question_key=q.question_key,
                type=q.type,
                stem=q.stem,
                options=q.options,
                knowledge_point=q.knowledge_point,
                difficulty=q.difficulty,
            )
            for q in questions
        ],
    )


@router.post("/exam/{exam_id}/submit", response_model=SubmitResponse)
async def submit_answers(
    body: SubmitRequest,
    exam_id: int = Path(...),
    session: Session = Depends(get_db),
) -> SubmitResponse:
    """提交答卷并判分。"""
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
            AnswerResultItem(
                question_key=q.question_key if q else "",
                is_correct=r.is_correct,
                user_answer=r.user_answer,
                correct_answer=q.answer if q else "",
                explanation=q.explanation if q else "",
                analysis=mistake.analysis if mistake else None,
            )
        )

    return SubmitResponse(
        submission_id=submission.id,  # type: ignore[arg-type]
        score=submission.score,
        results=results,
    )


@router.get("/subjects/{subject}/exam/history", response_model=ExamHistoryResponse)
async def get_exam_history(
    subject: str = Depends(validate_subject),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
) -> ExamHistoryResponse:
    """分页考试历史。"""
    from app.repositories.exam_repo import list_exam_history_by_subject

    items, total = list_exam_history_by_subject(
        session, subject, limit=pagination.limit, offset=pagination.offset
    )
    return ExamHistoryResponse(
        items=[
            ExamHistoryItem(
                exam_id=item["exam_id"],
                submission_id=item.get("submission_id"),
                score=item.get("score"),
                created_at=item["created_at"],
            )
            for item in items
        ],
        total=total,
    )
