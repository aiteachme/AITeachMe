"""
Exam + Question + ExamSubmission + AnswerRecord + Mistake CRUD
"""

from __future__ import annotations

from sqlmodel import Session, select, func

from app.repositories.models import (
    Exam,
    Question,
    ExamSubmission,
    AnswerRecord,
    Mistake,
)


# ─── Exam + Question ───


def create_exam_with_questions(
    session: Session, exam: Exam, questions: list[Question]
) -> tuple[Exam, list[Question]]:
    """创建考试及其题目。"""
    session.add(exam)
    session.commit()
    session.refresh(exam)

    for q in questions:
        q.exam_id = exam.id  # type: ignore[assignment]
        session.add(q)
    session.commit()
    for q in questions:
        session.refresh(q)

    return exam, questions


def get_exam_by_id(session: Session, exam_id: int) -> Exam | None:
    return session.get(Exam, exam_id)


def get_questions_by_exam_id(session: Session, exam_id: int) -> list[Question]:
    stmt = select(Question).where(Question.exam_id == exam_id)
    return list(session.exec(stmt).all())


# ─── ExamSubmission + AnswerRecord ───


def create_submission_with_records(
    session: Session,
    submission: ExamSubmission,
    records: list[AnswerRecord],
) -> tuple[ExamSubmission, list[AnswerRecord]]:
    """创建提交记录及答题记录。"""
    session.add(submission)
    session.commit()
    session.refresh(submission)

    for r in records:
        r.submission_id = submission.id  # type: ignore[assignment]
        session.add(r)
    session.commit()
    for r in records:
        session.refresh(r)

    return submission, records


def list_exam_history_by_subject(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[dict], int]:
    """
    按学科分页列表考试历史。
    返回 (items, total)，每个 item 包含 exam_id, submission_id, score, created_at。
    """
    count_stmt = select(func.count()).select_from(Exam).where(Exam.subject == subject)
    total = session.exec(count_stmt).one()

    stmt = (
        select(
            Exam.id,
            Exam.created_at,
            ExamSubmission.id,
            ExamSubmission.score,
        )
        .outerjoin(ExamSubmission, ExamSubmission.exam_id == Exam.id)
        .where(Exam.subject == subject)
        .order_by(Exam.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    items = [
        {
            "exam_id": row[0],
            "created_at": row[1],
            "submission_id": row[2],
            "score": row[3],
        }
        for row in rows
    ]
    return items, total


# ─── Mistake ───


def create_mistake(session: Session, mistake: Mistake) -> Mistake:
    session.add(mistake)
    session.commit()
    session.refresh(mistake)
    return mistake


def bulk_create_mistakes(session: Session, mistakes: list[Mistake]) -> list[Mistake]:
    for m in mistakes:
        session.add(m)
    session.commit()
    for m in mistakes:
        session.refresh(m)
    return mistakes


def list_mistakes_by_subject(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[dict], int]:
    """
    按学科分页列表错题（通过 answer_record → question → exam 进行 JOIN）。
    返回 (items, total)。
    """
    # 计算总数
    count_stmt = (
        select(func.count())
        .select_from(Mistake)
        .join(AnswerRecord, Mistake.answer_record_id == AnswerRecord.id)
        .join(Question, AnswerRecord.question_id == Question.id)
        .join(Exam, Question.exam_id == Exam.id)
        .where(Exam.subject == subject)
    )
    total = session.exec(count_stmt).one()

    # 查询错题详情
    stmt = (
        select(
            Mistake.id,
            Mistake.analysis,
            Mistake.created_at,
            Question.stem,
            Question.type,
            Question.answer,
            Question.knowledge_point,
            AnswerRecord.user_answer,
        )
        .join(AnswerRecord, Mistake.answer_record_id == AnswerRecord.id)
        .join(Question, AnswerRecord.question_id == Question.id)
        .join(Exam, Question.exam_id == Exam.id)
        .where(Exam.subject == subject)
        .order_by(Mistake.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    items = [
        {
            "id": row[0],
            "analysis": row[1],
            "created_at": row[2],
            "question_stem": row[3],
            "question_type": row[4],
            "correct_answer": row[5],
            "knowledge_point": row[6],
            "user_answer": row[7],
        }
        for row in rows
    ]
    return items, total
