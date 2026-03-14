"""
考试编排 — 协调 generator → 保存 → 返回，submit → grader → profile

需求：9.5, 10.1, 10.6
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.ai.examine.generator import generate_exam
from app.ai.examine.grader import grade_exam
from app.core.exceptions import ExamNotFoundError
from app.repositories import exam_repo
from app.repositories.models import (
    Exam,
    Question,
    ExamSubmission,
    AnswerRecord,
    Mistake,
)

logger = structlog.get_logger()


async def create_exam(
    session: Session,
    *,
    subject: str,
    num_questions: int = 10,
    difficulty_distribution: dict[str, float] | None = None,
    knowledge_points: list[str] | None = None,
) -> tuple[Exam, list[Question]]:
    """
    生成考卷并持久化。

    Returns:
        (exam, questions) — questions 不含 answer（由 API 层 DTO 过滤）
    """
    # 1. AI 生成题目
    questions = await generate_exam(
        session,
        subject=subject,
        num_questions=num_questions,
        difficulty_distribution=difficulty_distribution,
        knowledge_points=knowledge_points,
    )

    # 2. 持久化
    exam = Exam(subject=subject)
    exam, questions = exam_repo.create_exam_with_questions(session, exam, questions)

    logger.info("exam_created", exam_id=exam.id, subject=subject, questions=len(questions))
    return exam, questions


async def submit_exam(
    session: Session,
    *,
    exam_id: int,
    answers: dict[str, str],
) -> tuple[ExamSubmission, list[AnswerRecord], list[Mistake], list[Question]]:
    """
    提交答卷 → 判分 → profile 更新。

    Returns:
        (submission, answer_records, mistakes, questions)
    """
    # 1. 查找考卷
    exam = exam_repo.get_exam_by_id(session, exam_id)
    if exam is None:
        raise ExamNotFoundError(exam_id)

    questions = exam_repo.get_questions_by_exam_id(session, exam_id)

    # 2. 判分（含 profile 更新）
    submission, records, mistakes = await grade_exam(
        session,
        exam_id=exam_id,
        subject=exam.subject,
        questions=questions,
        answers=answers,
    )

    logger.info(
        "exam_submitted",
        exam_id=exam_id,
        score=submission.score,
        mistakes=len(mistakes),
    )
    return submission, records, mistakes, questions
