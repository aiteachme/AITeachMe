"""
自动判分与错题分析

客观题（single_choice、fill_blank）：确定性字符串比较
主观题（short_answer）：LLM 二元判分（0 或 1）
为每道错题生成 AI 错因分析，写入 Mistake 表
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.core.llm import acompletion
from app.agents.profile.tracker import update_profiles_from_grading
from app.repositories import exam_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.repositories.models import (
    Question,
    QuestionType,
    ExamSubmission,
    AnswerRecord,
    Mistake,
)

logger = structlog.get_logger()


async def grade_exam(
    session: Session,
    *,
    exam_id: int,
    subject: str,
    questions: list[Question],
    answers: dict[str, str],
) -> tuple[ExamSubmission, list[AnswerRecord], list[Mistake]]:
    """
    判分完整流程：

    1. 逐题判分（客观题确定性比较，主观题 LLM 判分）
    2. 计算总分 score = correct_count / total × 100
    3. 创建 ExamSubmission + AnswerRecord
    4. 为错题生成 AI 错因分析 → Mistake
    5. 触发 Profile 引擎更新掌握度

    Returns:
        (submission, answer_records, mistakes)
    """
    # 1. 逐题判分
    grading_results: list[dict] = []
    for q in questions:
        user_answer = answers.get(q.question_key, "")
        is_correct = await _grade_single(q, user_answer)
        grading_results.append({
            "question": q,
            "user_answer": user_answer,
            "is_correct": is_correct,
        })

    # 2. 计算总分
    total = len(questions)
    correct_count = sum(1 for r in grading_results if r["is_correct"])
    score = (correct_count / total * 100) if total > 0 else 0.0

    # 3. 创建 ExamSubmission + AnswerRecord
    submission = ExamSubmission(exam_id=exam_id, score=score)
    records = [
        AnswerRecord(
            submission_id=0,  # set by repo
            question_id=r["question"].id,
            user_answer=r["user_answer"],
            is_correct=r["is_correct"],
        )
        for r in grading_results
    ]
    submission, records = exam_repo.create_submission_with_records(
        session, submission, records
    )

    # 4. 为错题生成 AI 错因分析
    wrong_results = [
        (r, rec)
        for r, rec in zip(grading_results, records)
        if not r["is_correct"]
    ]
    mistakes: list[Mistake] = []
    for result, record in wrong_results:
        analysis = await _generate_mistake_analysis(result["question"], result["user_answer"])
        mistakes.append(Mistake(answer_record_id=record.id, analysis=analysis))

    if mistakes:
        mistakes = exam_repo.bulk_create_mistakes(session, mistakes)

    # 5. 触发 Profile 更新
    update_profiles_from_grading(
        session, subject=subject, grading_results=grading_results
    )

    logger.info(
        "exam_graded",
        exam_id=exam_id,
        total=total,
        correct=correct_count,
        score=round(score, 1),
        mistakes=len(mistakes),
    )

    return submission, records, mistakes


async def _grade_single(question: Question, user_answer: str) -> bool:
    """判分单道题目。"""
    q_type = question.type

    if q_type in (QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value):
        # 客观题：确定性字符串比较（忽略首尾空白、大小写）
        return user_answer.strip().lower() == question.answer.strip().lower()

    if q_type == QuestionType.SHORT_ANSWER.value:
        # 主观题：LLM 二元判分
        return await _llm_grade_short_answer(question, user_answer)

    # 未知题型，默认按字符串比较
    return user_answer.strip().lower() == question.answer.strip().lower()


async def _llm_grade_short_answer(question: Question, user_answer: str) -> bool:
    """LLM 二元判分：判断简答题是否基本正确（0 或 1）。"""
    messages = [
        ChatMessage(
            role=SYSTEM,
            content=(
                "你是一位严谨的阅卷老师。请判断学生的回答是否基本正确。\n"
                "只需回复 1（基本正确）或 0（不正确），不要输出其他内容。"
            ),
        ),
        ChatMessage(
            role=USER,
            content=(
                f"题目：{question.stem}\n"
                f"参考答案：{question.answer}\n"
                f"学生回答：{user_answer}\n\n"
                f"判分（1 或 0）："
            ),
        ),
    ]
    try:
        result = await acompletion(messages)
        return result.strip().startswith("1")
    except Exception:
        logger.warning("llm_grading_fallback", question_key=question.question_key)
        # LLM 失败时回退到字符串比较
        return user_answer.strip().lower() == question.answer.strip().lower()


async def _generate_mistake_analysis(question: Question, user_answer: str) -> str:
    """为错题生成 AI 错因分析。"""
    messages = [
        ChatMessage(
            role=SYSTEM,
            content="你是一位耐心的老师，请分析学生答错的原因并给出改进建议。简洁明了，100字以内。",
        ),
        ChatMessage(
            role=USER,
            content=(
                f"题目：{question.stem}\n"
                f"正确答案：{question.answer}\n"
                f"学生回答：{user_answer}\n"
                f"知识点：{question.knowledge_point}\n\n"
                f"请分析错因："
            ),
        ),
    ]
    try:
        return await acompletion(messages)
    except Exception:
        logger.warning("mistake_analysis_fallback", question_key=question.question_key)
        return "错因分析生成失败，请参考正确答案自行复习。"



