"""Runtime helpers for the examine workflow."""

from __future__ import annotations

import asyncio

import structlog
from pydantic import BaseModel, Field

from app.core.llm import acompletion, acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models import Difficulty, Question, QuestionType
from app.schemas.llm import SYSTEM, USER
from app.workflows.examine.prompts import (
    SYSTEM_PROMPT_EXAM_GENERATE,
    SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
    SYSTEM_PROMPT_MISTAKE_ANALYSIS,
    SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
)

logger = structlog.get_logger()


class GeneratedQuestion(BaseModel):
    """A generated question ready to be saved as an exam item."""

    question_key: str
    type: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_point: str
    difficulty: str


class GeneratedExam(BaseModel):
    """The structured exam payload returned by the LLM."""

    questions: list[GeneratedQuestion] = Field(min_length=1)


class GradingResultItem(BaseModel):
    """The grading result for a single question."""

    question_id: int
    question_key: str
    user_answer: str
    is_correct: bool
    analysis: str | None = None


class GradingResult(BaseModel):
    """The grading result for a full exam submission."""

    score: float
    items: list[GradingResultItem]


async def generate_exam(
    *,
    subject: str,
    num_questions: int,
    available_knowledge_points: list[str],
    weak_knowledge_points: list[str],
    recent_mistake_stems: list[str],
    requested_knowledge_points: list[str] | None = None,
) -> list[GeneratedQuestion]:
    """Generate an exam using profiles, mistakes, and knowledge points."""

    prompt = populate_prompt(
        SYSTEM_PROMPT_EXAM_GENERATE,
        subject=subject,
        num_questions=num_questions,
        available_knowledge_points=", ".join(available_knowledge_points[:50]) or "暂无",
        weak_knowledge_points=", ".join(weak_knowledge_points[:20]) or "暂无",
        requested_knowledge_points=", ".join(requested_knowledge_points or []) or "未指定",
        recent_mistake_stems="\n".join(f"- {item}" for item in recent_mistake_stems[:10]) or "- 无",
        question_types=", ".join(item.value for item in QuestionType),
        difficulties=", ".join(item.value for item in Difficulty),
    )
    result = await acompletion_structured(
        response_model=GeneratedExam,
        messages=[{"role": SYSTEM, "content": prompt}],
    )
    logger.info("generate_exam_complete", subject=subject, question_count=len(result.questions))
    return result.questions


async def generate_exam_from_text(
    *,
    subject: str,
    knowledge_text: str,
    num_questions: int,
) -> list[GeneratedQuestion]:
    """Generate an exam directly from raw knowledge text."""

    prompt = populate_prompt(
        SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
        subject=subject,
        num_questions=num_questions,
        knowledge_text=knowledge_text,
        question_types=", ".join(item.value for item in QuestionType),
        difficulties=", ".join(item.value for item in Difficulty),
    )
    result = await acompletion_structured(
        response_model=GeneratedExam,
        messages=[{"role": SYSTEM, "content": prompt}],
    )
    return result.questions


async def grade_exam(
    *,
    questions: list[Question],
    answers: dict[str, str],
) -> GradingResult:
    """Grade an exam and attach mistake analysis for incorrect answers."""

    if not questions:
        return GradingResult(score=0.0, items=[])

    grade_tasks = [
        grade_one_question(question=question, user_answer=answers.get(question.question_key, ""))
        for question in questions
    ]
    grade_results = await asyncio.gather(*grade_tasks)

    incorrect_indices = [
        index
        for index, is_correct in enumerate(grade_results)
        if not is_correct
    ]
    analysis_tasks = [
        generate_mistake_analysis(
            questions[index],
            answers.get(questions[index].question_key, ""),
        )
        for index in incorrect_indices
    ]
    analysis_results = await asyncio.gather(*analysis_tasks) if analysis_tasks else []
    analysis_map = dict(zip(incorrect_indices, analysis_results))

    items = [
        GradingResultItem(
            question_id=question.id or 0,
            question_key=question.question_key,
            user_answer=answers.get(question.question_key, ""),
            is_correct=is_correct,
            analysis=analysis_map.get(index),
        )
        for index, (question, is_correct) in enumerate(zip(questions, grade_results))
    ]
    correct_count = sum(1 for item in items if item.is_correct)
    return GradingResult(score=correct_count / len(questions) * 100, items=items)


async def grade_one_question(*, question: Question, user_answer: str) -> bool:
    """Grade one question, using strict matching for objective questions."""

    if question.type in {QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value}:
        return user_answer.strip().lower() == question.answer.strip().lower()

    prompt = populate_prompt(
        SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
        stem=question.stem,
        answer=question.answer,
        user_answer=user_answer,
    )
    try:
        result = await acompletion(
            messages=[
                {"role": SYSTEM, "content": "你是一名严谨的阅卷老师。"},
                {"role": USER, "content": prompt},
            ]
        )
        return result.strip().startswith("1")
    except Exception:
        logger.warning("grade_short_answer_fallback", question_key=question.question_key)
        return user_answer.strip().lower() == question.answer.strip().lower()


async def generate_mistake_analysis(question: Question, user_answer: str) -> str:
    """Generate a short explanation for an incorrect answer."""

    prompt = populate_prompt(
        SYSTEM_PROMPT_MISTAKE_ANALYSIS,
        stem=question.stem,
        answer=question.answer,
        user_answer=user_answer,
        knowledge_point=question.knowledge_point,
    )
    try:
        return await acompletion(
            messages=[
                {"role": SYSTEM, "content": "你是一名耐心的老师。"},
                {"role": USER, "content": prompt},
            ]
        )
    except Exception:
        logger.warning("mistake_analysis_fallback", question_key=question.question_key)
        return "错因分析生成失败，请结合标准答案再次复习。"
