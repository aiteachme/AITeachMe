"""测验数据访问层。"""

from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import AnswerRecord, Exam, ExamSubmission, Mistake, Question


def create_exam_with_questions(
    session: Session,
    exam: Exam,
    questions: list[Question],
) -> tuple[Exam, list[Question]]:
    """创建试卷与题目。"""

    session.add(exam)
    session.commit()
    session.refresh(exam)
    if exam.id is None:
        raise ValueError("Exam.id 持久化后不应为空。")

    for question in questions:
        question.exam_id = exam.id
        session.add(question)
    session.commit()
    for question in questions:
        session.refresh(question)
    return exam, questions


def get_exam_by_id(session: Session, exam_id: int) -> Exam | None:
    """按 ID 查询试卷。"""

    return session.get(Exam, exam_id)


def get_questions_by_exam_id(session: Session, exam_id: int) -> list[Question]:
    """查询试卷题目。"""

    return list(session.exec(select(Question).where(Question.exam_id == exam_id)).all())


def create_submission_with_records(
    session: Session,
    submission: ExamSubmission,
    records: list[AnswerRecord],
) -> tuple[ExamSubmission, list[AnswerRecord]]:
    """创建交卷记录与作答记录。"""

    session.add(submission)
    session.commit()
    session.refresh(submission)
    if submission.id is None:
        raise ValueError("ExamSubmission.id 持久化后不应为空。")

    for record in records:
        record.submission_id = submission.id
        session.add(record)
    session.commit()
    for record in records:
        session.refresh(record)
    return submission, records


def bulk_create_mistakes(session: Session, mistakes: list[Mistake]) -> list[Mistake]:
    """批量写入错题记录。"""

    for mistake in mistakes:
        session.add(mistake)
    session.commit()
    for mistake in mistakes:
        session.refresh(mistake)
    return mistakes


def list_exam_history_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """分页查询试卷历史。"""

    total = session.exec(select(func.count()).select_from(Exam).where(Exam.subject == subject)).one()
    rows = session.exec(
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
    ).all()
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


def list_mistakes_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """分页查询错题本。"""

    total = session.exec(
        select(func.count())
        .select_from(Mistake)
        .join(AnswerRecord, Mistake.answer_record_id == AnswerRecord.id)
        .join(Question, AnswerRecord.question_id == Question.id)
        .join(Exam, Question.exam_id == Exam.id)
        .where(Exam.subject == subject)
    ).one()
    rows = session.exec(
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
    ).all()
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


def delete_exam_cascade(session: Session, exam_id: int) -> bool:
    """级联删除试卷及其关联数据。"""

    exam = session.get(Exam, exam_id)
    if exam is None:
        return False

    questions = get_questions_by_exam_id(session, exam_id)
    submissions = list(
        session.exec(select(ExamSubmission).where(ExamSubmission.exam_id == exam_id)).all()
    )

    for submission in submissions:
        records = list(
            session.exec(
                select(AnswerRecord).where(AnswerRecord.submission_id == submission.id)
            ).all()
        )
        for record in records:
            mistakes = list(
                session.exec(
                    select(Mistake).where(Mistake.answer_record_id == record.id)
                ).all()
            )
            for mistake in mistakes:
                session.delete(mistake)
            session.delete(record)
        session.delete(submission)

    for question in questions:
        session.delete(question)

    session.delete(exam)
    session.commit()
    return True
