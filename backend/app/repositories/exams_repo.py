"""Exam data access layer."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from app.models import (
    AnswerRecord,
    CurriculumSnapshot,
    Exam,
    ExamPaper,
    ExamPaperGenerationContext,
    ExamPaperItem,
    ExamSubmission,
    Mistake,
    PrereqDagVersion,
    Question,
    QuestionTemplate,
    QuestionTemplateNodeLink,
    ReviewTask,
    TeachingUnit,
    UnitDependency,
    UnitTreeMembership,
    UserAnswerAttempt,
)
from app.repositories.knowledge import curriculum_repo


# ---------------------------------------------------------------------------
# Legacy Exam CRUD (table: exam / question / submission)
# ---------------------------------------------------------------------------


def create_exam_with_questions(
    session: Session,
    exam: Exam,
    questions: list[Question],
) -> tuple[Exam, list[Question]]:
    session.add(exam)
    session.commit()
    session.refresh(exam)
    if exam.id is None:
        raise ValueError("Exam.id should not be None after persistence.")

    for question in questions:
        question.exam_id = exam.id
        session.add(question)
    session.commit()
    for question in questions:
        session.refresh(question)
    return exam, questions


def get_exam_by_id(session: Session, exam_id: int) -> Exam | None:
    return session.get(Exam, exam_id)


def get_questions_by_exam_id(session: Session, exam_id: int) -> list[Question]:
    return list(session.exec(select(Question).where(Question.exam_id == exam_id)).all())


def create_submission_with_records(
    session: Session,
    submission: ExamSubmission,
    records: list[AnswerRecord],
) -> tuple[ExamSubmission, list[AnswerRecord]]:
    session.add(submission)
    session.commit()
    session.refresh(submission)
    if submission.id is None:
        raise ValueError("ExamSubmission.id should not be None after persistence.")

    for record in records:
        record.submission_id = submission.id
        session.add(record)
    session.commit()
    for record in records:
        session.refresh(record)
    return submission, records


def bulk_create_mistakes(session: Session, mistakes: list[Mistake]) -> list[Mistake]:
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
    exam = session.get(Exam, exam_id)
    if exam is None:
        return False

    questions = get_questions_by_exam_id(session, exam_id)
    submissions = list(session.exec(select(ExamSubmission).where(ExamSubmission.exam_id == exam_id)).all())

    for submission in submissions:
        records = list(session.exec(select(AnswerRecord).where(AnswerRecord.submission_id == submission.id)).all())
        for record in records:
            mistakes = list(session.exec(select(Mistake).where(Mistake.answer_record_id == record.id)).all())
            for mistake in mistakes:
                session.delete(mistake)
            session.delete(record)
        session.delete(submission)

    for question in questions:
        session.delete(question)

    session.delete(exam)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# New ExamPaper + QuestionTemplate CRUD
# ---------------------------------------------------------------------------


def create_question_template(session: Session, template: QuestionTemplate) -> QuestionTemplate:
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def create_template_node_links(
    session: Session,
    links: list[QuestionTemplateNodeLink],
) -> list[QuestionTemplateNodeLink]:
    for item in links:
        session.add(item)
    session.commit()
    for item in links:
        session.refresh(item)
    return links


def find_templates_by_unit(
    session: Session,
    unit_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).where(QuestionTemplate.teaching_unit_id == unit_id)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def find_templates_by_node(
    session: Session,
    node_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = (
        select(QuestionTemplate)
        .join(QuestionTemplateNodeLink, QuestionTemplateNodeLink.question_template_id == QuestionTemplate.id)
        .where(QuestionTemplateNodeLink.knowledge_node_id == node_id)
    )
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.distinct().order_by(QuestionTemplate.id)).all())


def find_template_by_stem_hash(
    session: Session,
    subject: str,
    unit_id: int,
    stem_hash: str,
) -> QuestionTemplate | None:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.teaching_unit_id == unit_id,
        QuestionTemplate.stem_hash == stem_hash,
    )
    return session.exec(stmt).first()


def find_node_links_by_template(session: Session, template_id: int) -> list[QuestionTemplateNodeLink]:
    stmt = select(QuestionTemplateNodeLink).where(QuestionTemplateNodeLink.question_template_id == template_id)
    return list(session.exec(stmt.order_by(QuestionTemplateNodeLink.id)).all())


def create_exam_paper(session: Session, paper: ExamPaper) -> ExamPaper:
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def create_exam_paper_items(session: Session, items: list[ExamPaperItem]) -> list[ExamPaperItem]:
    for item in items:
        session.add(item)
    session.commit()
    for item in items:
        session.refresh(item)
    return items


def create_generation_context(
    session: Session,
    ctx: ExamPaperGenerationContext,
) -> ExamPaperGenerationContext:
    session.add(ctx)
    session.commit()
    session.refresh(ctx)
    return ctx


def get_exam_paper_by_id(session: Session, paper_id: int) -> ExamPaper | None:
    return session.get(ExamPaper, paper_id)


def list_exam_papers(
    session: Session,
    *,
    subject: str,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[ExamPaper], int]:
    total = session.exec(
        select(func.count())
        .select_from(ExamPaper)
        .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
    ).one()
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
            .order_by(ExamPaper.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def list_teaching_unit_ids_by_subject(
    session: Session,
    *,
    subject: str,
    status: str | None = "active",
) -> list[int]:
    stmt = select(TeachingUnit.id).where(TeachingUnit.subject == subject)
    if status is not None:
        stmt = stmt.where(TeachingUnit.status == status)
    stmt = stmt.order_by(TeachingUnit.id)
    return [int(item) for item in session.exec(stmt).all() if item is not None]


def count_active_question_templates(
    session: Session,
    *,
    subject: str,
    question_types: set[str] | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(QuestionTemplate)
        .where(
            QuestionTemplate.subject == subject,
            QuestionTemplate.status == "active",
        )
    )
    if question_types:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_types))  # type: ignore[union-attr]
    return int(session.exec(stmt).one())


def list_exam_item_snapshots_by_user(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[tuple[ExamPaperItem, datetime, int]]:
    stmt = (
        select(ExamPaperItem, ExamPaper.created_at, ExamPaper.id)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.subject == subject,
            ExamPaper.user_id == user_id,
        )
        .order_by(ExamPaper.created_at.desc(), ExamPaper.id.desc(), ExamPaperItem.item_order.asc())  # type: ignore[union-attr]
    )
    rows = list(session.exec(stmt).all())
    normalized: list[tuple[ExamPaperItem, datetime, int]] = []
    for row in rows:
        item, asked_at, exam_paper_id = row
        normalized.append((item, asked_at, int(exam_paper_id)))
    return normalized


def delete_exam_paper_cascade(session: Session, *, paper_id: int) -> bool:
    paper = session.get(ExamPaper, paper_id)
    if paper is None:
        return False

    item_ids = [
        int(item_id)
        for item_id in session.exec(select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id == paper_id)).all()
        if item_id is not None
    ]

    if item_ids:
        attempts = list(
            session.exec(
                select(UserAnswerAttempt).where(UserAnswerAttempt.exam_paper_item_id.in_(item_ids))  # type: ignore[union-attr]
            ).all()
        )
        for item in attempts:
            session.delete(item)

        paper_items = list(
            session.exec(select(ExamPaperItem).where(ExamPaperItem.id.in_(item_ids))).all()  # type: ignore[union-attr]
        )
        for item in paper_items:
            session.delete(item)

    generation_contexts = list(
        session.exec(select(ExamPaperGenerationContext).where(ExamPaperGenerationContext.exam_paper_id == paper_id)).all()
    )
    for item in generation_contexts:
        session.delete(item)

    review_tasks = list(session.exec(select(ReviewTask).where(ReviewTask.source_exam_paper_id == paper_id)).all())
    for item in review_tasks:
        session.delete(item)

    session.delete(paper)
    session.commit()
    return True


def create_answer_attempts(
    session: Session,
    attempts: list[UserAnswerAttempt],
) -> list[UserAnswerAttempt]:
    for item in attempts:
        session.add(item)
    session.commit()
    for item in attempts:
        session.refresh(item)
    return attempts


def list_attempts_by_paper(session: Session, paper_id: int) -> list[UserAnswerAttempt]:
    stmt = (
        select(UserAnswerAttempt)
        .join(ExamPaperItem, UserAnswerAttempt.exam_paper_item_id == ExamPaperItem.id)
        .where(ExamPaperItem.exam_paper_id == paper_id)
        .order_by(UserAnswerAttempt.id)
    )
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# Cross-table reads for paper assembly
# ---------------------------------------------------------------------------


def get_published_curriculum_snapshot(
    session: Session,
    subject: str,
) -> CurriculumSnapshot | None:
    return curriculum_repo.get_current_curriculum_snapshot(session, subject)


def resolve_teaching_units_from_theme_tree_node(
    session: Session,
    theme_tree_node_id: int,
) -> list[int]:
    stmt = (
        select(UnitTreeMembership.teaching_unit_id)
        .where(UnitTreeMembership.tree_node_id == theme_tree_node_id)
        .distinct()
        .order_by(UnitTreeMembership.teaching_unit_id)
    )
    return [int(item) for item in session.exec(stmt).all()]


def list_prereq_units(session: Session, unit_id: int) -> list[int]:
    unit = session.get(TeachingUnit, unit_id)
    if unit is None:
        return []

    dag_id = session.exec(
        select(PrereqDagVersion.id)
        .where(
            PrereqDagVersion.subject == unit.subject,
            PrereqDagVersion.status == "published",
        )
        .order_by(PrereqDagVersion.version_no.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()
    if dag_id is None:
        return []

    stmt = (
        select(UnitDependency.source_unit_id)
        .where(
            UnitDependency.dag_version_id == dag_id,
            UnitDependency.target_unit_id == unit_id,
            UnitDependency.dependency_type == "prerequisite",
        )
        .distinct()
        .order_by(UnitDependency.source_unit_id)
    )
    return [int(item) for item in session.exec(stmt).all()]


def list_recent_exam_template_ids_for_user(
    session: Session,
    user_id: str,
    subject: str,
    *,
    limit: int = 3,
) -> list[int]:
    if limit <= 0:
        return []

    recent_exam_ids_subquery = (
        select(ExamPaper.id)
        .where(ExamPaper.user_id == user_id, ExamPaper.subject == subject)
        .order_by(ExamPaper.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
        .subquery()
    )

    stmt = (
        select(ExamPaperItem.question_template_id)
        .where(ExamPaperItem.exam_paper_id.in_(select(recent_exam_ids_subquery.c.id)))
        .distinct()
    )
    return [int(item) for item in session.exec(stmt).all()]
