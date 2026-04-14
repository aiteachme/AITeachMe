"""Question template build workflow trigger."""

from __future__ import annotations

import json

import structlog
from sqlmodel import Session

from app.shared.infra.observability import llm_trace_scope
from app.utils.time import utcnow
from app.workflows.examine.context import ExamStyleProfile
from app.workflows.examine.question_build_workflow import QuestionBuildWorkflow

from ._helpers import QuestionBuildResult, _new_runtime_job_id

logger = structlog.get_logger()


async def trigger_question_build(
    session: Session,
    *,
    subject: str,
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int,
    exam_mode: str,
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile: ExamStyleProfile | None = None,
    curriculum_version_id: int | None = None,
    template_context_signature: str | None = None,
    context_locked: bool = False,
    scope_locked: bool = False,
    focus_teaching_unit_ids: list[int] | None = None,
    focus_node_ids: list[int] | None = None,
) -> QuestionBuildResult:
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    resolved_questions_per_unit = max(1, int(questions_per_unit))

    try:
        with llm_trace_scope(
            subject=subject,
            build_session_id=str(runtime_job_id),
            workflow="examine.question_build",
            lane="question_build",
            node="generate_templates",
        ):
            state = await QuestionBuildWorkflow.run(
                subject=subject,
                user_id=user_id,
                unit_ids=unit_ids,
                questions_per_unit=resolved_questions_per_unit,
                job_id=runtime_job_id,
                exam_mode=exam_mode,
                preferred_question_types=preferred_question_types or [],
                user_prompt=user_prompt,
                focus_prompt=focus_prompt,
                style_profile=style_profile,
                curriculum_version_id=curriculum_version_id,
                template_context_signature=template_context_signature,
                context_locked=context_locked,
                scope_locked=scope_locked,
                focus_teaching_unit_ids=focus_teaching_unit_ids or [],
                focus_node_ids=focus_node_ids or [],
                session=session,
            )
        error = state.get("error")
        updated_at = utcnow()
        return QuestionBuildResult(
            id=runtime_job_id,
            subject=subject,
            status="failed" if error else "completed",
            templates_created=int(state.get("templates_created", 0)),
            warnings_json=json.dumps(state.get("warnings", []), ensure_ascii=False),
            error_message=str(error) if error else None,
            created_at=created_at,
            updated_at=updated_at,
        )
    except Exception as exc:  # noqa: BLE001
        updated_at = utcnow()
        logger.error(
            "trigger_question_build_failed",
            subject=subject,
            user_id=user_id,
            error=str(exc),
            exc_info=True,
        )
        return QuestionBuildResult(
            id=runtime_job_id,
            subject=subject,
            status="failed",
            templates_created=0,
            warnings_json="[]",
            error_message=str(exc),
            created_at=created_at,
            updated_at=updated_at,
        )
