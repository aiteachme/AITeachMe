"""Examine 默认考卷后台生成触发器。

这个模块刻意不实现考题生成，只组装 exams API 现有的默认配置，
然后委托给已经存在的隐藏考卷后台生成链路。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic

import structlog

from app.models import Course, exam_mode_value
from app.repositories import exams_repo
from app.shared.infra.database import managed_session

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class ExamPrewarmTriggerResult:
    """请求既有隐藏考卷后台生成链路后的结果。"""

    status: str
    course_id: str
    user_id: str
    exam_mode: str
    num_questions: int
    reason: str = ""


async def trigger_default_exam_prewarm_for_course(
    *,
    course_id: str,
    user_id: str | None = None,
    min_build_revision_no: int | None = None,
    wait_for_units_timeout_s: float = 0.0,
    poll_interval_s: float = 5.0,
) -> ExamPrewarmTriggerResult:
    """为课程触发现有的默认隐藏考卷后台生成链路。"""

    from app.api.exams import (  # imported lazily to avoid changing exam generation logic
        _build_exam_config_snapshot,
        _exam_config_hash,
        _exam_mastery_fingerprint,
        _list_exam_eligible_units,
        _run_exam_prewarm_background,
        default_auto_prewarm_exam_config,
    )

    default_config = default_auto_prewarm_exam_config()
    exam_mode = exam_mode_value(str(default_config.get("exam_mode") or "web_practice"))
    question_count = int(default_config.get("question_count") or 24)
    user_prompt_value = default_config.get("user_prompt")
    user_prompt = user_prompt_value if isinstance(user_prompt_value, str) and user_prompt_value.strip() else None
    sample_file_ids = [
        str(file_id).strip()
        for file_id in default_config.get("sample_file_ids") or []
        if str(file_id).strip()
    ]
    paper_layout_value = default_config.get("paper_layout_mode")
    paper_layout_mode = (
        str(paper_layout_value).strip()
        if paper_layout_value is not None and str(paper_layout_value).strip()
        else None
    )
    deadline = monotonic() + max(0.0, float(wait_for_units_timeout_s or 0.0))
    owner_user_id = user_id or ""

    while True:
        with managed_session() as session:
            course = session.get(Course, course_id)
            if course is None:
                return ExamPrewarmTriggerResult(
                    status="skipped",
                    course_id=course_id,
                    user_id=user_id or "",
                    exam_mode=exam_mode,
                    num_questions=question_count,
                    reason="course_not_found",
                )
            owner_user_id = user_id or course.user_id
            if owner_user_id != course.user_id:
                return ExamPrewarmTriggerResult(
                    status="skipped",
                    course_id=course_id,
                    user_id=owner_user_id,
                    exam_mode=exam_mode,
                    num_questions=question_count,
                    reason="course_owner_mismatch",
                )
            units = _list_exam_eligible_units(session, course_id=course_id)
            if min_build_revision_no is not None:
                units = [
                    unit
                    for unit in units
                    if int(getattr(unit, "build_revision_no", 0) or 0) >= int(min_build_revision_no)
                ]
            unit_ids = [int(unit.id or 0) for unit in units if unit.id is not None]
            if unit_ids:
                config_snapshot = _build_exam_config_snapshot(
                    course_id=course_id,
                    user_id=owner_user_id,
                    exam_mode=exam_mode,
                    question_count=question_count,
                    user_prompt=user_prompt,
                    sample_file_ids=sample_file_ids,
                    knowledge_unit_ids=unit_ids,
                    mastery_fingerprint=_exam_mastery_fingerprint(session, course_id=course_id, user_id=owner_user_id),
                    paper_layout_mode=paper_layout_mode,
                )
                config_hash = _exam_config_hash(config_snapshot)
                if exams_repo.has_active_prepared_exam(
                    session,
                    course_id=course_id,
                    user_id=owner_user_id,
                    config_hash=config_hash,
                ):
                    return ExamPrewarmTriggerResult(
                        status="exists",
                        course_id=course_id,
                        user_id=owner_user_id,
                        exam_mode=exam_mode,
                        num_questions=question_count,
                        reason="active_prepared_exam_exists",
                    )
                break

        if monotonic() >= deadline:
            return ExamPrewarmTriggerResult(
                status="skipped",
                course_id=course_id,
                user_id=owner_user_id,
                exam_mode=exam_mode,
                num_questions=question_count,
                reason="no_active_knowledge_units",
            )
        await asyncio.sleep(max(0.5, float(poll_interval_s or 5.0)))

    await _run_exam_prewarm_background(
        course_id=course_id,
        user_id=owner_user_id,
        exam_mode=exam_mode,
        unit_ids=unit_ids,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
    )
    logger.info(
        "exam_default_prewarm_requested_for_synced_units",
        course_id=course_id,
        user_id=owner_user_id,
        question_count=question_count,
    )
    return ExamPrewarmTriggerResult(
        status="requested",
        course_id=course_id,
        user_id=owner_user_id,
        exam_mode=exam_mode,
        num_questions=question_count,
    )


__all__ = ["ExamPrewarmTriggerResult", "trigger_default_exam_prewarm_for_course"]
