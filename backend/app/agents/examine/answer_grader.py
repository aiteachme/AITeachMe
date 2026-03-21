"""判卷器：判分 + 错因标注。"""

from __future__ import annotations

import json
from datetime import datetime

import structlog
from pydantic import BaseModel
from sqlmodel import Session, select

from app.agents.examine.prompts import (
    SYSTEM_PROMPT_ERROR_CAUSE_LABEL,
    SYSTEM_PROMPT_MISTAKE_ANALYSIS,
    SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
)
from app.core.llm import acompletion
from app.core.prompt_loader import populate_prompt
from app.models import ErrorCauseLabel, ExamPaper, ExamPaperItem, KnowledgeNode, QuestionType, UserAnswerAttempt
from app.repositories import assessment_repo
from app.schemas.llm import SYSTEM, USER
from app.utils.time import utcnow

logger = structlog.get_logger()


def normalize_answer(text: str) -> str:
    """答案标准化：去首尾空白 + 小写。"""

    return (text or "").strip().lower()


def exact_match_grade(user_answer: str, correct_answer: str) -> bool:
    """精确匹配判分（基于 normalize 结果）。"""

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

    node_ids = [item.get("knowledge_node_id") for item in links if isinstance(item, dict)]
    node_ids = [int(node_id) for node_id in node_ids if isinstance(node_id, int)]
    if not node_ids:
        return ""

    names: list[str] = []
    for node_id in node_ids:
        node = session.get(KnowledgeNode, node_id)
        if node is not None:
            names.append(node.canonical_name)
    return ", ".join(names)


def _grade_short_answer_with_llm(*, stem: str, correct_answer: str, user_answer: str) -> bool:
    prompt = populate_prompt(
        SYSTEM_PROMPT_SHORT_ANSWER_GRADE,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
    )
    result = acompletion(
        messages=[
            {"role": SYSTEM, "content": "你是一名严谨的阅卷老师。"},
            {"role": USER, "content": prompt},
        ]
    )
    if hasattr(result, "__await__"):  # 兼容异步函数返回协程对象
        import asyncio

        result = asyncio.run(result)
    return str(result).strip().startswith("1")


def _infer_error_cause_label(
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
        knowledge_context=knowledge_context or "无",
    )
    try:
        result = acompletion(
            messages=[
                {"role": SYSTEM, "content": "你是一名擅长诊断学习错误原因的老师。"},
                {"role": USER, "content": prompt},
            ]
        )
        if hasattr(result, "__await__"):
            import asyncio

            result = asyncio.run(result)
        normalized = str(result).strip().lower()
        allowed = {item.value for item in ErrorCauseLabel}
        if normalized in allowed:
            return normalized
    except Exception as exc:  # noqa: BLE001
        logger.warning("answer_grader_error_label_llm_failed", error=str(exc))
    return ErrorCauseLabel.UNKNOWN.value


def _generate_mistake_analysis(
    *,
    stem: str,
    correct_answer: str,
    user_answer: str,
    knowledge_context: str,
) -> str:
    prompt = populate_prompt(
        SYSTEM_PROMPT_MISTAKE_ANALYSIS,
        stem=stem,
        answer=correct_answer,
        user_answer=user_answer,
        knowledge_point=knowledge_context or "未知知识点",
    )
    result = acompletion(
        messages=[
            {"role": SYSTEM, "content": "你是一名耐心的老师。"},
            {"role": USER, "content": prompt},
        ]
    )
    if hasattr(result, "__await__"):
        import asyncio

        result = asyncio.run(result)
    return str(result)


def grade_paper(session: Session, exam_paper_id: int) -> GradeResult:
    """对试卷全部 UserAnswerAttempt 判分，并更新试卷状态。"""

    exam_paper = session.get(ExamPaper, exam_paper_id)
    if exam_paper is None:
        raise ValueError(f"ExamPaper `{exam_paper_id}` not found.")

    attempts = assessment_repo.list_attempts_by_paper(session, exam_paper_id)
    items = list(
        session.exec(
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id)
        ).all()
    )
    item_by_id = {item.id: item for item in items if item.id is not None}

    graded_items: list[GradeResultItem] = []
    correct_items = 0

    for attempt in attempts:
        item = item_by_id.get(attempt.exam_paper_item_id)
        if item is None:
            continue

        # 幂等：已判分记录不重复覆盖
        if attempt.is_correct is not None:
            score_max = attempt.score_max if attempt.score_max is not None else 1.0
            score_obtained = attempt.score_obtained if attempt.score_obtained is not None else (1.0 if attempt.is_correct else 0.0)
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

        user_answer = attempt.user_answer or ""
        correct_answer = item.snapshot_answer or ""
        question_type = item.snapshot_question_type

        if question_type in {QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value}:
            is_correct = exact_match_grade(user_answer, correct_answer)
        else:
            try:
                is_correct = _grade_short_answer_with_llm(
                    stem=item.snapshot_stem,
                    correct_answer=correct_answer,
                    user_answer=user_answer,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("answer_grader_short_answer_fallback", error=str(exc))
                is_correct = exact_match_grade(user_answer, correct_answer)

        attempt.is_correct = is_correct
        attempt.score_max = 1.0
        attempt.score_obtained = 1.0 if is_correct else 0.0

        if not is_correct:
            knowledge_context = _build_knowledge_context(session, item)
            attempt.error_cause_label = _infer_error_cause_label(
                stem=item.snapshot_stem,
                correct_answer=correct_answer,
                user_answer=user_answer,
                knowledge_context=knowledge_context,
            )
            # 为后续错因文本能力预留调用，不影响当前结构化标签主流程
            try:
                _generate_mistake_analysis(
                    stem=item.snapshot_stem,
                    correct_answer=correct_answer,
                    user_answer=user_answer,
                    knowledge_context=knowledge_context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("answer_grader_mistake_analysis_failed", error=str(exc))
        else:
            attempt.error_cause_label = None

        session.add(attempt)

        if is_correct:
            correct_items += 1
        graded_items.append(
            GradeResultItem(
                attempt_id=attempt.id or 0,
                exam_paper_item_id=attempt.exam_paper_item_id,
                is_correct=is_correct,
                score_obtained=attempt.score_obtained,
                score_max=attempt.score_max,
                error_cause_label=attempt.error_cause_label,
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
