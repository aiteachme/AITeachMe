"""Runtime helpers for the examine workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models import Difficulty, QuestionType
from app.schemas.llm import SYSTEM
from app.workflows.examine.prompts import SYSTEM_PROMPT_EXAM_GENERATE_FROM_TEXT


class GeneratedQuestion(BaseModel):
    """A generated question payload."""

    question_type: str
    difficulty: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_node_id: int | None = None


class GeneratedExam(BaseModel):
    """Structured exam payload returned by the LLM."""

    questions: list[GeneratedQuestion] = Field(min_length=1)


async def generate_exam_from_text(
    *,
    subject: str,
    knowledge_text: str,
    num_questions: int,
) -> list[GeneratedQuestion]:
    """Generate exam questions directly from raw knowledge text.

    This helper is retained for playground/debug usage only.
    """

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
