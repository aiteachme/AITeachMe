"""测验判卷 Agent。"""

from __future__ import annotations

import asyncio

import structlog
from pydantic import BaseModel

from app.agents.examine.prompts import (
    SYSTEM_PROMPT_MISTAKE_ANALYSIS,
    SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
)
from app.core.llm import acompletion
from app.core.prompt_loader import populate_prompt
from app.models import Question, QuestionType
from app.schemas.llm import SYSTEM, USER

logger = structlog.get_logger()


class GradingResultItem(BaseModel):
    """单题判分结果。"""

    question_id: int
    question_key: str
    user_answer: str
    is_correct: bool
    analysis: str | None = None


class GradingResult(BaseModel):
    """整张试卷判分结果。"""

    score: float
    items: list[GradingResultItem]


async def grade_exam(
    *,
    questions: list[Question],
    answers: dict[str, str],
) -> GradingResult:
    """对整张试卷判分（并行化：先批量判分，再批量生成错因分析）。"""

    if not questions:
        return GradingResult(score=0.0, items=[])

    # 第一轮：并行判分
    grade_tasks = [
        grade_one_question(question=q, user_answer=answers.get(q.question_key, ""))
        for q in questions
    ]
    grade_results = await asyncio.gather(*grade_tasks)

    # 第二轮：并行生成错因分析（仅错题）
    incorrect_indices: list[int] = []
    analysis_tasks: list = []
    for i, (question, is_correct) in enumerate(zip(questions, grade_results)):
        if not is_correct:
            incorrect_indices.append(i)
            analysis_tasks.append(
                generate_mistake_analysis(question, answers.get(question.question_key, ""))
            )

    analysis_results = await asyncio.gather(*analysis_tasks) if analysis_tasks else []
    analysis_map: dict[int, str] = dict(zip(incorrect_indices, analysis_results))

    # 组装结果
    items: list[GradingResultItem] = []
    correct_count = 0
    for i, (question, is_correct) in enumerate(zip(questions, grade_results)):
        if is_correct:
            correct_count += 1
        items.append(
            GradingResultItem(
                question_id=question.id or 0,
                question_key=question.question_key,
                user_answer=answers.get(question.question_key, ""),
                is_correct=is_correct,
                analysis=analysis_map.get(i),
            )
        )

    score = correct_count / len(questions) * 100
    return GradingResult(score=score, items=items)


async def grade_one_question(*, question: Question, user_answer: str) -> bool:
    """对单题判分。"""

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
    """生成错因分析。"""

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
