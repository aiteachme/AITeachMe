"""测验服务层。"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.examine import generate_exam, grade_exam
from app.core.exceptions import ExamNotFoundError
from app.models import AnswerRecord, Exam, ExamSubmission, Mistake, Question
from app.repositories.exams_repo import (
    bulk_create_mistakes,
    create_exam_with_questions,
    create_submission_with_records,
    delete_exam_cascade,
    get_exam_by_id,
    get_questions_by_exam_id,
    list_exam_history_by_subject,
    list_mistakes_by_subject,
)
from app.repositories.knowledge.kg_repo import list_nodes_by_subject
from app.repositories.profile_repo import get_profile_by_key, get_weak_points, upsert_profile
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.exams import (
    AnswerResultItem,
    ExamData,
    ExamDeleteData,
    ExamHistoryItem,
    QuestionItem,
    SubmitData,
)
from app.services.presenters import require_id


async def create_exam(
    session: Session,
    *,
    subject: str,
    num_questions: int,
    knowledge_points: list[str] | None = None,
) -> ExamData:
    """生成并保存试卷。"""

    nodes, _ = list_nodes_by_subject(session, subject, limit=500, offset=0)
    available_knowledge_points = list({node.canonical_name for node in nodes})
    weak_knowledge_points = [item.knowledge_point for item in get_weak_points(session, subject, limit=20)]
    recent_mistakes, _ = list_mistakes_by_subject(session, subject, limit=20, offset=0)
    generated_questions = await generate_exam(
        subject=subject,
        num_questions=num_questions,
        available_knowledge_points=available_knowledge_points,
        weak_knowledge_points=weak_knowledge_points,
        recent_mistake_stems=[item["question_stem"] for item in recent_mistakes],
        requested_knowledge_points=knowledge_points,
    )
    exam = Exam(subject=subject)
    db_questions = [
        Question(
            exam_id=0,
            question_key=item.question_key,
            type=item.type,
            stem=item.stem,
            options=item.options if item.type == "single_choice" else None,
            answer=item.answer,
            explanation=item.explanation,
            knowledge_point=item.knowledge_point,
            difficulty=item.difficulty,
        )
        for item in generated_questions
    ]
    exam, questions = create_exam_with_questions(session, exam, db_questions)
    return ExamData(
        exam_id=require_id(exam.id, "Exam.id"),
        questions=[_to_question_item(item) for item in questions],
    )


async def submit_exam(
    session: Session,
    *,
    subject: str,
    exam_id: int,
    answers: dict[str, str],
) -> SubmitData:
    """提交试卷并判卷。"""

    exam = get_exam_by_id(session, exam_id)
    if exam is None or exam.subject != subject:
        raise ExamNotFoundError(exam_id)
    questions = get_questions_by_exam_id(session, exam_id)
    grading_result = await grade_exam(questions=questions, answers=answers)

    submission, records = create_submission_with_records(
        session,
        ExamSubmission(exam_id=exam_id, score=grading_result.score),
        [
            AnswerRecord(
                submission_id=0,
                question_id=item.question_id,
                user_answer=item.user_answer,
                is_correct=item.is_correct,
            )
            for item in grading_result.items
        ],
    )
    record_by_question_id = {record.question_id: record for record in records}
    mistakes = bulk_create_mistakes(
        session,
        [
            Mistake(
                answer_record_id=require_id(record_by_question_id[item.question_id].id, "AnswerRecord.id"),
                analysis=item.analysis or "",
            )
            for item in grading_result.items
            if not item.is_correct and item.analysis
        ],
    )
    mistake_by_record_id = {mistake.answer_record_id: mistake for mistake in mistakes}

    _update_profiles_from_grading(session, subject=subject, questions=questions, grading_items=grading_result.items)

    question_by_id = {require_id(question.id, "Question.id"): question for question in questions}
    results: list[AnswerResultItem] = []
    for item in grading_result.items:
        question = question_by_id[item.question_id]
        record = record_by_question_id[item.question_id]
        mistake = mistake_by_record_id.get(require_id(record.id, "AnswerRecord.id"))
        results.append(
            AnswerResultItem(
                question_key=item.question_key,
                is_correct=item.is_correct,
                user_answer=item.user_answer,
                correct_answer=question.answer,
                explanation=question.explanation,
                analysis=mistake.analysis if mistake else None,
            )
        )

    return SubmitData(
        submission_id=require_id(submission.id, "ExamSubmission.id"),
        score=submission.score,
        results=results,
    )


def list_exams(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[ExamHistoryItem]:
    """分页读取试卷历史。"""

    items, total = list_exam_history_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[
            ExamHistoryItem(
                exam_id=item["exam_id"],
                submission_id=item.get("submission_id"),
                score=item.get("score"),
                created_at=item["created_at"],
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


def delete_exam(
    session: Session,
    *,
    subject: str,
    exam_id: int,
) -> ExamDeleteData:
    """删除试卷。"""

    exam = get_exam_by_id(session, exam_id)
    if exam is None or exam.subject != subject:
        raise ExamNotFoundError(exam_id)
    delete_exam_cascade(session, exam_id)
    return ExamDeleteData(deleted=True, exam_id=exam_id)


def _to_question_item(question: Question) -> QuestionItem:
    return QuestionItem(
        question_key=question.question_key,
        type=question.type,
        stem=question.stem,
        options=question.options,
        knowledge_point=question.knowledge_point,
        difficulty=question.difficulty,
    )


def _update_profiles_from_grading(
    session: Session,
    *,
    subject: str,
    questions: list[Question],
    grading_items: list[object],
) -> None:
    """根据判卷结果更新学习画像。"""

    question_by_id = {require_id(question.id, "Question.id"): question for question in questions}
    stats: dict[str, dict[str, int]] = {}
    for item in grading_items:
        question = question_by_id[item.question_id]
        if question.knowledge_point not in stats:
            stats[question.knowledge_point] = {"attempts": 0, "correct": 0}
        stats[question.knowledge_point]["attempts"] += 1
        if item.is_correct:
            stats[question.knowledge_point]["correct"] += 1

    for knowledge_point, state in stats.items():
        profile = get_profile_by_key(
            session,
            user_id="local",
            subject=subject,
            knowledge_point=knowledge_point,
        )
        prev_attempts = profile.attempts if profile else 0
        prev_correct = profile.correct if profile else 0
        upsert_profile(
            session,
            user_id="local",
            subject=subject,
            knowledge_point=knowledge_point,
            attempts=prev_attempts + state["attempts"],
            correct=prev_correct + state["correct"],
        )
