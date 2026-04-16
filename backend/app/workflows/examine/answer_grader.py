"""Exam grader that writes grading results onto ExamPaperItem rows."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from sqlmodel import Session

from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.prompt_loader import populate_prompt
from app.models import ErrorCauseLabel, ExamPaper, ExamPaperItem, QuestionType
from app.repositories import exams_repo
from app.schemas.llm import SYSTEM, USER
from app.utils.time import utcnow
from app.workflows.examine.context import (
    build_grading_knowledge_context,
    read_knowledge_doc_text,
)
from app.workflows.examine.exam_grade.prompts import (
    SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
    SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
)

logger = structlog.get_logger()

_MAX_CONCURRENT_GRADE_LLM_CALLS = 12


def normalize_answer(text: str) -> str:
    return (text or "").strip().lower()


def exact_match_grade(user_answer: str, correct_answer: str) -> bool:
    return normalize_answer(user_answer) == normalize_answer(correct_answer)


class GradeResultItem(BaseModel):
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


def _extract_node_ids(raw_refs: str | None) -> list[int]:
    try:
        decoded = json.loads(raw_refs or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []

    node_ids: list[int] = []
    for item in decoded:
        if not isinstance(item, dict):
            continue
        raw_node_id = item.get("knowledge_unit_id")
        if isinstance(raw_node_id, int) and raw_node_id > 0:
            node_ids.append(raw_node_id)
        elif isinstance(raw_node_id, str) and raw_node_id.isdigit():
            node_ids.append(int(raw_node_id))
    return list(dict.fromkeys(node_ids))


def _build_knowledge_context(
    session: Session,
    exam_paper: ExamPaper,
    exam_paper_item: ExamPaperItem,
    *,
    knowledge_doc_text: str,
) -> str:
    return build_grading_knowledge_context(
        session,
        subject=exam_paper.subject,
        teaching_unit_id=exam_paper_item.teaching_unit_id,
        node_ids=_extract_node_ids(exam_paper_item.knowledge_unit_refs_json),
        knowledge_doc_text=knowledge_doc_text,
    )


async def _run_bounded_llm_call(
    semaphore: asyncio.Semaphore | None,
    coro,
):
    if semaphore is None:
        return await coro
    async with semaphore:
        return await coro


async def _grade_short_answer_with_llm(
    *,
    stem: str,
    correct_answer: str,
    user_answer: str,
    knowledge_context: str,
    semaphore: asyncio.Semaphore | None = None,
) -> bool:
    prompt = populate_prompt(
        SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
        knowledge_context=knowledge_context or "none",
    )
    result = await _run_bounded_llm_call(
        semaphore,
        acompletion(
            messages=[
                {"role": SYSTEM, "content": "You are a strict but fair grader."},
                {"role": USER, "content": prompt},
            ],
            task_type=TaskType.GRADE,
        ),
    )
    return str(result).strip().startswith("1")


async def _infer_error_cause_label(
    *,
    stem: str,
    correct_answer: str,
    user_answer: str,
    knowledge_context: str,
    semaphore: asyncio.Semaphore | None = None,
) -> str | None:
    prompt = populate_prompt(
        SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
        knowledge_context=knowledge_context or "none",
    )
    try:
        result = await _run_bounded_llm_call(
            semaphore,
            acompletion(
                messages=[
                    {"role": SYSTEM, "content": "You diagnose likely learning mistake causes."},
                    {"role": USER, "content": prompt},
                ],
                task_type=TaskType.GRADE,
            ),
        )
        normalized = str(result).strip().lower()
        allowed = {item.value for item in ErrorCauseLabel}
        if normalized in allowed and normalized != ErrorCauseLabel.UNKNOWN.value:
            return normalized
    except Exception as exc:  # noqa: BLE001
        logger.warning("answer_grader_error_label_llm_failed", error=str(exc))
    return None


@dataclass
class _ItemContext:
    item: ExamPaperItem
    user_answer: str
    correct_answer: str
    question_type: str
    knowledge_context: str = ""
    is_correct: bool | None = None
    error_cause_label: str | None = None


async def grade_paper(
    session: Session,
    exam_paper_id: int,
    *,
    auto_commit: bool = True,
) -> GradeResult:
    """Grade all items for a paper and persist grading fields."""

    exam_paper = session.get(ExamPaper, exam_paper_id)
    if exam_paper is None:
        raise ValueError(f"ExamPaper `{exam_paper_id}` not found.")

    items = exams_repo.list_items_by_paper(session, exam_paper_id)
    objective_types = {QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value}

    graded_items: list[GradeResultItem] = []
    correct_items = 0
    to_grade: list[_ItemContext] = []

    for item in items:
        if item.answer_content is None:
            continue

        if item.is_correct is not None:
            score_max = item.score_max if item.score_max is not None else 1.0
            score_obtained = item.score_obtained if item.score_obtained is not None else (1.0 if item.is_correct else 0.0)
            if item.is_correct:
                correct_items += 1
            graded_items.append(
                GradeResultItem(
                    exam_paper_item_id=item.id or 0,
                    is_correct=item.is_correct,
                    score_obtained=score_obtained,
                    score_max=score_max,
                    error_cause_label=item.error_cause_label,
                )
            )
            continue

        to_grade.append(
            _ItemContext(
                item=item,
                user_answer=item.answer_content or "",
                correct_answer=item.answer_snapshot or "",
                question_type=item.question_type,
            )
        )

    knowledge_doc_text = read_knowledge_doc_text(exam_paper.subject)
    knowledge_contexts = {
        index: _build_knowledge_context(
            session,
            exam_paper,
            entry.item,
            knowledge_doc_text=knowledge_doc_text,
        )
        for index, entry in enumerate(to_grade)
        if entry.question_type == QuestionType.SHORT_ANSWER.value
    }
    for index, knowledge_context in knowledge_contexts.items():
        to_grade[index].knowledge_context = knowledge_context

    llm_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GRADE_LLM_CALLS)

    short_answer_indices = [
        index
        for index, entry in enumerate(to_grade)
        if entry.question_type not in objective_types
    ]
    if short_answer_indices:
        logger.info(
            "answer_grader_short_answer_batch_started",
            exam_paper_id=exam_paper_id,
            batch_size=len(short_answer_indices),
            concurrency_limit=_MAX_CONCURRENT_GRADE_LLM_CALLS,
        )
        short_answer_results = await asyncio.gather(
            *[
                _grade_short_answer_with_llm(
                    stem=to_grade[index].item.stem_snapshot,
                    correct_answer=to_grade[index].correct_answer,
                    user_answer=to_grade[index].user_answer,
                    knowledge_context=to_grade[index].knowledge_context,
                    semaphore=llm_semaphore,
                )
                for index in short_answer_indices
            ],
            return_exceptions=True,
        )
        for index, result in zip(short_answer_indices, short_answer_results):
            if isinstance(result, Exception):
                logger.error(
                    "answer_grader_short_answer_failed",
                    exam_paper_id=exam_paper_id,
                    exam_paper_item_id=to_grade[index].item.id,
                    error=str(result),
                )
                raise RuntimeError(
                    f"short_answer_grading_failed:item={to_grade[index].item.id or index}: {result}"
                ) from result
            to_grade[index].is_correct = bool(result)

    for entry in to_grade:
        if entry.is_correct is None:
            if entry.question_type == QuestionType.SHORT_ANSWER.value:
                raise RuntimeError(
                    f"short_answer_grading_missing:item={entry.item.id or 0}"
                )
            entry.is_correct = exact_match_grade(entry.user_answer, entry.correct_answer)

    wrong_short_answer_indices = [
        index
        for index, entry in enumerate(to_grade)
        if entry.is_correct is False and entry.question_type == QuestionType.SHORT_ANSWER.value
    ]
    if wrong_short_answer_indices:
        logger.info(
            "answer_grader_error_label_batch_started",
            exam_paper_id=exam_paper_id,
            batch_size=len(wrong_short_answer_indices),
            concurrency_limit=_MAX_CONCURRENT_GRADE_LLM_CALLS,
        )
        label_results = await asyncio.gather(
            *[
                _infer_error_cause_label(
                    stem=to_grade[index].item.stem_snapshot,
                    correct_answer=to_grade[index].correct_answer,
                    user_answer=to_grade[index].user_answer,
                    knowledge_context=to_grade[index].knowledge_context,
                    semaphore=llm_semaphore,
                )
                for index in wrong_short_answer_indices
            ],
            return_exceptions=True,
        )
        for index, result in zip(wrong_short_answer_indices, label_results):
            if isinstance(result, Exception):
                logger.warning("answer_grader_error_label_llm_failed", error=str(result))
                to_grade[index].error_cause_label = None
            else:
                to_grade[index].error_cause_label = str(result) if result is not None else None

    for entry in to_grade:
        if entry.is_correct:
            entry.error_cause_label = None
        elif entry.question_type != QuestionType.SHORT_ANSWER.value:
            entry.error_cause_label = None

        entry.item.is_correct = entry.is_correct
        entry.item.score_max = 1.0
        entry.item.score_obtained = 1.0 if entry.is_correct else 0.0
        entry.item.error_cause_label = entry.error_cause_label
        entry.item.feedback_text = (
            None
            if entry.is_correct
            else (entry.knowledge_context[:300] if entry.knowledge_context else entry.item.explanation_snapshot)
        )
        entry.item.graded_at = utcnow()
        entry.item.updated_at = utcnow()
        session.add(entry.item)

        if entry.is_correct:
            correct_items += 1
        graded_items.append(
            GradeResultItem(
                exam_paper_item_id=entry.item.id or 0,
                is_correct=entry.is_correct,
                score_obtained=entry.item.score_obtained or 0.0,
                score_max=entry.item.score_max or 1.0,
                error_cause_label=entry.item.error_cause_label,
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
    if auto_commit:
        session.commit()
        session.refresh(exam_paper)
    else:
        session.flush()

    return GradeResult(
        exam_paper_id=exam_paper_id,
        total_items=total_items,
        correct_items=correct_items,
        score=score,
        graded_items=graded_items,
    )
