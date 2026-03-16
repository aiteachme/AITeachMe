"""测验出题 Agent。"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from app.agents.examine.prompts import (
    SYSTEM_PROMPT_EXAM_GENERATE,
    SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT,
)
from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models import Difficulty, QuestionType
from app.schemas.llm import SYSTEM

logger = structlog.get_logger()


class GeneratedQuestion(BaseModel):
    """生成后的题目。"""

    question_key: str
    type: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_point: str
    difficulty: str


class GeneratedExam(BaseModel):
    """生成后的试卷。"""

    questions: list[GeneratedQuestion] = Field(min_length=1)


async def generate_exam(
    *,
    subject: str,
    num_questions: int,
    available_knowledge_points: list[str],
    weak_knowledge_points: list[str],
    recent_mistake_stems: list[str],
    requested_knowledge_points: list[str] | None = None,
) -> list[GeneratedQuestion]:
    """根据知识点与画像信息生成试题。"""

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
    """根据纯文本知识内容直接出题，供 playground 使用。"""

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
