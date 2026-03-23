"""判卷器：判分 + 错因标注。

Reads DB: ``exam_paper``, ``exam_paper_item``, ``user_answer_attempt`` and referenced knowledge nodes.
Writes DB: graded ``user_answer_attempt`` fields such as correctness, scores and error labels.
Writes FS: none.
Idempotency: reruns recompute grading for the same attempts and overwrite grading fields in place.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.core.prompt_loader import populate_prompt
from app.models import (
    ErrorCauseLabel,
    ExamPaper,
    ExamPaperItem,
    KnowledgeNode,
    QuestionType,
    UserAnswerAttempt,
)
from app.repositories import exams_repo
from app.schemas.llm import SYSTEM, USER
from app.utils.time import utcnow
from app.workflows.examine.prompts import (
    SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
    SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
)

logger = structlog.get_logger()


def normalize_answer(text: str) -> str:
    """Normalize answer text for exact-match grading."""

    return (text or "").strip().lower()


def exact_match_grade(user_answer: str, correct_answer: str) -> bool:
    """Exact-match grade using normalized answer strings."""

    return normalize_answer(user_answer) == normalize_answer(correct_answer)


class GradeResultItem(BaseModel):
    attempt_id: int
    exam_paper_item_id: int
    is_correct: bool
    score_obtained: float
    score_max: float
    error_cause_label: str | None = None


class GradeResult(BaseModel):
    exam_paper_id: int
    total_items: int
    correct_items: int
    score: float
    graded_items: list[GradeResultItem]


def _build_knowledge_context(session: Session, exam_paper_item: ExamPaperItem) -> str:
    try:
        links = json.loads(exam_paper_item.snapshot_node_links_json or "[]")
    except json.JSONDecodeError:
        links = []
    if not isinstance(links, list):
        return ""

    node_ids: list[int] = []
    for item in links:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("knowledge_node_id")
        if isinstance(raw_id, int):
            node_ids.append(raw_id)
        elif isinstance(raw_id, str) and raw_id.isdigit():
            node_ids.append(int(raw_id))

    if not node_ids:
        return ""

    names = [
        node.canonical_name
        for node_id in node_ids
        if (node := session.get(KnowledgeNode, node_id)) is not None
    ]
    return ", ".join(names)


async def _grade_short_answer_with_llm(
    *,
    stem: str,
    correct_answer: str,
    user_answer: str,
) -> bool:
    prompt = populate_prompt(
        SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
    )
    result = await acompletion(
        messages=[
            {"role": SYSTEM, "content": "You are a strict but fair grader."},
            {"role": USER, "content": prompt},
        ],
        task_type=TaskType.GRADE,
    )
    return str(result).strip().startswith("1")


async def _infer_error_cause_label(
    *,
    stem: str,
    correct_answer: str,
    user_answer: str,
    knowledge_context: str,
) -> str:
    prompt = populate_prompt(
        SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
        knowledge_context=knowledge_context or "none",
    )
    try:
        result = await acompletion(
            messages=[
                {"role": SYSTEM, "content": "You diagnose likely learning mistake causes."},
                {"role": USER, "content": prompt},
            ],
            task_type=TaskType.GRADE,
        )
        normalized = str(result).strip().lower()
        allowed = {item.value for item in ErrorCauseLabel}
        if normalized in allowed:
            return normalized
    except Exception as exc:  # noqa: BLE001
        logger.warning("answer_grader_error_label_llm_failed", error=str(exc))
    return ErrorCauseLabel.UNKNOWN.value


@dataclass
class _AttemptContext:
    attempt: UserAnswerAttempt
    item: ExamPaperItem
    user_answer: str
    correct_answer: str
    question_type: str
    is_correct: bool | None = None
    error_cause_label: str | None = None


async def grade_paper(session: Session, exam_paper_id: int) -> GradeResult:
    """Grade all attempts for a paper and persist grading fields."""

    exam_paper = session.get(ExamPaper, exam_paper_id)
    if exam_paper is None:
        raise ValueError(f"ExamPaper `{exam_paper_id}` not found.")

    attempts = exams_repo.list_attempts_by_paper(session, exam_paper_id)
    items = list(
        session.exec(
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id)
        ).all()
    )
    item_by_id = {item.id: item for item in items if item.id is not None}

    graded_items: list[GradeResultItem] = []
    correct_items = 0

    objective_types = {QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value}
    to_grade: list[_AttemptContext] = []
    for attempt in attempts:
        item = item_by_id.get(attempt.exam_paper_item_id)
        if item is None:
            continue

        if attempt.is_correct is not None:
            score_max = attempt.score_max if attempt.score_max is not None else 1.0
            score_obtained = attempt.score_obtained
            if score_obtained is None:
                score_obtained = 1.0 if attempt.is_correct else 0.0
            if attempt.is_correct:
                correct_items += 1
            graded_items.append(
                GradeResultItem(
                    attempt_id=attempt.id or 0,
                    exam_paper_item_id=attempt.exam_paper_item_id,
                    is_correct=attempt.is_correct,
                    score_obtained=score_obtained,
                    score_max=score_max,
                    error_cause_label=attempt.error_cause_label,
                )
            )
            continue

        to_grade.append(
            _AttemptContext(
                attempt=attempt,
                item=item,
                user_answer=attempt.user_answer or "",
                correct_answer=item.snapshot_answer or "",
                question_type=item.snapshot_question_type,
            )
        )

    # 1) Grade short-answer questions concurrently.
    short_answer_indices = [
        idx
        for idx, entry in enumerate(to_grade)
        if entry.question_type not in objective_types
    ]
    if short_answer_indices:
        short_answer_tasks = [
            _grade_short_answer_with_llm(
                stem=to_grade[idx].item.snapshot_stem,
                correct_answer=to_grade[idx].correct_answer,
                user_answer=to_grade[idx].user_answer,
            )
            for idx in short_answer_indices
        ]
        short_answer_results = await asyncio.gather(*short_answer_tasks, return_exceptions=True)
        for idx, result in zip(short_answer_indices, short_answer_results):
            if isinstance(result, Exception):
                logger.warning("answer_grader_short_answer_fallback", error=str(result))
                to_grade[idx].is_correct = exact_match_grade(
                    to_grade[idx].user_answer,
                    to_grade[idx].correct_answer,
                )
            else:
                to_grade[idx].is_correct = bool(result)

    for entry in to_grade:
        if entry.is_correct is None:
            entry.is_correct = exact_match_grade(entry.user_answer, entry.correct_answer)

    # 2) Infer labels for wrong short-answer questions concurrently.
    wrong_short_answer_indices = [
        idx
        for idx, entry in enumerate(to_grade)
        if (entry.is_correct is False and entry.question_type == QuestionType.SHORT_ANSWER.value)
    ]
    if wrong_short_answer_indices:
        contexts = {
            idx: _build_knowledge_context(session, to_grade[idx].item)
            for idx in wrong_short_answer_indices
        }
        label_tasks = [
            _infer_error_cause_label(
                stem=to_grade[idx].item.snapshot_stem,
                correct_answer=to_grade[idx].correct_answer,
                user_answer=to_grade[idx].user_answer,
                knowledge_context=contexts[idx],
            )
            for idx in wrong_short_answer_indices
        ]
        label_results = await asyncio.gather(*label_tasks, return_exceptions=True)
        for idx, result in zip(wrong_short_answer_indices, label_results):
            if isinstance(result, Exception):
                logger.warning("answer_grader_error_label_llm_failed", error=str(result))
                to_grade[idx].error_cause_label = ErrorCauseLabel.UNKNOWN.value
            else:
                to_grade[idx].error_cause_label = str(result)

    for entry in to_grade:
        if entry.is_correct:
            entry.error_cause_label = None
        elif entry.error_cause_label is None:
            # Avoid extra LLM latency on objective-question mistakes.
            entry.error_cause_label = ErrorCauseLabel.UNKNOWN.value

        entry.attempt.is_correct = entry.is_correct
        entry.attempt.score_max = 1.0
        entry.attempt.score_obtained = 1.0 if entry.is_correct else 0.0
        entry.attempt.error_cause_label = entry.error_cause_label
        session.add(entry.attempt)

        if entry.is_correct:
            correct_items += 1
        graded_items.append(
            GradeResultItem(
                attempt_id=entry.attempt.id or 0,
                exam_paper_item_id=entry.attempt.exam_paper_item_id,
                is_correct=entry.is_correct,
                score_obtained=entry.attempt.score_obtained,
                score_max=entry.attempt.score_max,
                error_cause_label=entry.attempt.error_cause_label,
            )
        )

    total_items = len(items)
    score = (correct_items / total_items * 100.0) if total_items > 0 else 0.0

    exam_paper.status = "graded"
    exam_paper.graded_at = utcnow()
    exam_paper.total_score = float(total_items)
    exam_paper.score_obtained = float(correct_items)
    exam_paper.updated_at = utcnow()
    session.add(exam_paper)
    session.commit()
    session.refresh(exam_paper)

    return GradeResult(
        exam_paper_id=exam_paper_id,
        total_items=total_items,
        correct_items=correct_items,
        score=score,
        graded_items=graded_items,
    )
