"""Exam paper generation orchestrator."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter

import structlog
from sqlmodel import Session

from app.models import ExamMode, is_paper_exam_mode, is_web_practice_mode
from app.repositories import exams_repo
from app.shared.infra.exceptions import NoPublishedCurriculumSnapshotError
from app.shared.infra.observability.trace import llm_trace_scope
from app.utils.time import utcnow
from app.workflows.examine.context import (
    build_exam_style_profile,
    build_template_context_signature,
    has_explicit_exam_context,
)
from app.workflows.examine.paper_assembler import assemble_paper
from app.workflows.examine.paper_exporter import export_exam_paper_artifacts

from ._helpers import (
    ExamGenerationResult,
    QuestionBuildResult,
    _acquire_exam_generate_lock,
    _choose_default_question_count,
    _choose_preferred_question_types,
    _compile_paper_export_async,
    _count_effective_template_inventory,
    _elapsed_ms,
    _estimate_questions_per_unit,
    _extract_requested_question_count,
    _new_runtime_job_id,
    _parse_json_object,
    _prioritize_build_unit_ids,
    _raise_conflict,
    _resolve_auto_build_unit_ids,
    _resolve_generate_mode,
    _resolve_requested_unit_scope,
    _resolve_template_count_difficulty,
    _track_background_task,
)
from .question_build import trigger_question_build

logger = structlog.get_logger()


async def trigger_exam_generate(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    difficulty: str | None = None,
    num_questions: int | None = None,
    user_prompt: str | None = None,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    sample_file_uids: list[str] | None = None,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
) -> ExamGenerationResult:
    started_at = perf_counter()
    raw_mode = exam_mode.value if isinstance(exam_mode, ExamMode) else str(exam_mode or "")
    mode = _resolve_generate_mode(exam_mode)
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    build_session_id = f"exam_generate_{runtime_job_id}"
    lock = await _acquire_exam_generate_lock(subject=subject, user_id=user_id)

    try:
        snapshot = exams_repo.get_published_curriculum_version(session, subject)
        if snapshot is None or snapshot.id is None:
            raise NoPublishedCurriculumSnapshotError(subject)

        style_profile_started_at = perf_counter()
        style_profile = build_exam_style_profile(
            session,
            subject=subject,
            user_id=user_id,
            sample_file_uids=sample_file_uids,
            style_prompt=style_prompt,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            difficulty=difficulty,
            exam_mode=mode,
        )
        style_profile_ms = _elapsed_ms(style_profile_started_at)
        prompt_requested_count = _extract_requested_question_count(user_prompt)
        resolved_num_questions = (
            prompt_requested_count
            or (int(num_questions) if num_questions is not None else None)
            or style_profile.recommended_question_count
            or _choose_default_question_count(mode)
        )
        preferred_question_types = _choose_preferred_question_types(mode, user_prompt, style_profile)
        resolved_scope_unit_ids = _resolve_requested_unit_scope(
            session,
            subject=subject,
            teaching_unit_ids=teaching_unit_ids,
            theme_tree_node_id=theme_tree_node_id,
        )
        scope_locked = bool(teaching_unit_ids) or theme_tree_node_id is not None
        if scope_locked and not resolved_scope_unit_ids:
            _raise_conflict(
                "当前指定范围内没有可用教学单元，无法生成试卷。",
                error_code="EXAM_GENERATE_EMPTY_SCOPE",
            )
        build_unit_ids = _resolve_auto_build_unit_ids(
            session,
            subject=subject,
            teaching_unit_ids=teaching_unit_ids,
            theme_tree_node_id=theme_tree_node_id,
        )
        if not build_unit_ids:
            _raise_conflict(
                "当前学科没有可用教学单元，无法自动构题。",
                error_code="EXAM_GENERATE_NO_TEACHING_UNITS",
            )

        questions_per_unit = _estimate_questions_per_unit(
            num_questions=max(1, int(resolved_num_questions)),
            unit_count=len(build_unit_ids),
            mode=mode,
        )
        if not scope_locked:
            build_unit_ids = _prioritize_build_unit_ids(
                session,
                subject=subject,
                user_id=user_id,
                candidate_unit_ids=build_unit_ids,
                mode=mode,
                required_question_count=max(1, int(resolved_num_questions)),
                questions_per_unit=questions_per_unit,
                style_profile=style_profile,
            )
        required_template_count = max(1, int(resolved_num_questions))
        context_locked = has_explicit_exam_context(
            style_prompt=style_prompt,
            focus_prompt=focus_prompt,
            sample_file_uids=sample_file_uids,
            teaching_unit_ids=teaching_unit_ids,
            theme_tree_node_id=theme_tree_node_id,
        )
        inventory_unit_ids = (
            resolved_scope_unit_ids
            if scope_locked
            else (
                build_unit_ids
                if is_web_practice_mode(mode)
                else exams_repo.list_teaching_unit_ids_by_subject(session, subject=subject, status="active")
            )
        )
        template_context_signature = build_template_context_signature(
            curriculum_version_id=snapshot.id,
            exam_mode=mode,
            preferred_question_types=preferred_question_types,
            difficulty_focus=style_profile.difficulty_focus,
            context_locked=context_locked,
            scope_locked=scope_locked,
            scope_unit_ids=resolved_scope_unit_ids,
            style_prompt=style_prompt,
            focus_prompt=focus_prompt,
            sample_file_uids=sample_file_uids,
        )
        build_job: QuestionBuildResult | None = None
        question_build_ms = 0
        assemble_paper_ms = 0
        template_count_difficulty = _resolve_template_count_difficulty(style_profile.difficulty_focus)

        with llm_trace_scope(
            subject=subject,
            build_session_id=build_session_id,
            workflow="examine.generate",
            lane="generation",
            node="trigger_exam_generate",
        ):
            template_count_before = _count_effective_template_inventory(
                session,
                subject=subject,
                curriculum_version_id=snapshot.id,
                unit_ids=inventory_unit_ids,
                preferred_question_types=preferred_question_types,
                difficulty=template_count_difficulty,
                template_context_signature=template_context_signature,
                context_locked=context_locked,
            )
            if template_count_before < required_template_count:
                question_build_started_at = perf_counter()
                build_job = await trigger_question_build(
                    session,
                    subject=subject,
                    user_id=user_id,
                    unit_ids=build_unit_ids,
                    questions_per_unit=questions_per_unit,
                    exam_mode=mode,
                    preferred_question_types=preferred_question_types,
                    user_prompt=user_prompt,
                    focus_prompt=focus_prompt,
                    style_profile=style_profile,
                    curriculum_version_id=snapshot.id,
                    template_context_signature=template_context_signature,
                    context_locked=context_locked,
                    scope_locked=scope_locked,
                    focus_teaching_unit_ids=(resolved_scope_unit_ids or style_profile.focus_teaching_unit_ids),
                    focus_node_ids=style_profile.focus_node_ids,
                )
                question_build_ms = _elapsed_ms(question_build_started_at)
            else:
                logger.info(
                    "exam_generate_skip_question_build",
                    runtime_job_id=runtime_job_id,
                    subject=subject,
                    user_id=user_id,
                    template_count=template_count_before,
                    required_template_count=required_template_count,
                )

            template_count = _count_effective_template_inventory(
                session,
                subject=subject,
                curriculum_version_id=snapshot.id,
                unit_ids=inventory_unit_ids,
                preferred_question_types=preferred_question_types,
                difficulty=template_count_difficulty,
                template_context_signature=template_context_signature,
                context_locked=context_locked,
            )
            if template_count <= 0 and build_job is not None and build_job.status == "failed":
                raise ValueError(build_job.error_message or "自动构题失败，且没有可用题模板。")
            if template_count <= 0:
                raise ValueError("自动构题后仍没有可用题模板。")

            assemble_paper_started_at = perf_counter()
            paper = assemble_paper(
                session,
                subject=subject,
                user_id=user_id,
                exam_mode=mode,
                num_questions=max(1, int(resolved_num_questions)),
                curriculum_version_id=snapshot.id,
                theme_tree_node_id=theme_tree_node_id,
                teaching_unit_ids=(resolved_scope_unit_ids or (build_unit_ids if is_web_practice_mode(mode) else None)),
                preferred_question_types=preferred_question_types,
                preferred_difficulty=style_profile.difficulty_focus,
                style_profile=style_profile,
                user_prompt=user_prompt,
                focus_prompt=focus_prompt,
                sample_file_uids=sample_file_uids or [],
                template_context_signature=template_context_signature,
                context_locked=context_locked,
                scope_locked=scope_locked,
            )
            assemble_paper_ms = _elapsed_ms(assemble_paper_started_at)
            export_ms = 0
            if is_paper_exam_mode(mode):
                export_started_at = perf_counter()
                export_result = export_exam_paper_artifacts(
                    session,
                    paper=paper,
                    compile_pdf=False,
                )
                export_context = _parse_json_object(paper.selection_context_json)
                export_payload = export_result.model_dump()
                export_payload["pdf_compile_status"] = "pending"
                export_context["export_artifacts"] = export_payload
                paper.selection_context_json = json.dumps(export_context, ensure_ascii=False)
                paper.updated_at = utcnow()
                session.add(paper)
                session.commit()
                session.refresh(paper)
                export_ms = _elapsed_ms(export_started_at)
                logger.info(
                    "exam_generate_paper_export_staged",
                    runtime_job_id=runtime_job_id,
                    subject=subject,
                    user_id=user_id,
                    exam_paper_id=paper.id,
                    markdown_path=export_result.markdown_path,
                    tex_path=export_result.tex_path,
                    export_ms=export_ms,
                )
                if export_result.tex_path and paper.id is not None:
                    compile_task = asyncio.create_task(
                        _compile_paper_export_async(
                            exam_paper_id=int(paper.id),
                            tex_path=export_result.tex_path,
                            runtime_job_id=runtime_job_id,
                            subject=subject,
                            user_id=user_id,
                        )
                    )
                    _track_background_task(compile_task)

        updated_at = utcnow()
        logger.info(
            "exam_generate_timing_summary",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            raw_exam_mode=raw_mode,
            exam_mode=mode,
            workflow_elapsed_ms=_elapsed_ms(started_at),
            style_profile_ms=style_profile_ms,
            question_build_ms=question_build_ms,
            assemble_paper_ms=assemble_paper_ms,
            paper_export_ms=(export_ms if is_paper_exam_mode(mode) else 0),
            question_build_triggered=build_job is not None,
            question_build_status=(build_job.status if build_job is not None else "skipped"),
        )
        logger.info(
            "exam_generate_completed",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            exam_paper_id=paper.id,
            exam_mode=mode,
            num_questions=resolved_num_questions,
            teaching_unit_count=len(build_unit_ids),
            sample_file_count=len(sample_file_uids or []),
            user_prompt_present=bool((user_prompt or "").strip()),
            style_prompt_present=bool((style_prompt or "").strip()),
            focus_prompt_present=bool((focus_prompt or "").strip()),
            difficulty_focus=style_profile.difficulty_focus,
            build_unit_ids=build_unit_ids,
        )
        return ExamGenerationResult(
            id=runtime_job_id,
            status="completed",
            error_message=None,
            created_at=created_at,
            updated_at=updated_at,
            subject=subject,
            user_id=user_id,
            exam_mode=mode,
            num_questions=max(1, int(resolved_num_questions)),
            exam_paper_id=paper.id,
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids_json=json.dumps((resolved_scope_unit_ids or build_unit_ids), ensure_ascii=False),
            sample_file_uids_json=json.dumps(sample_file_uids or [], ensure_ascii=False),
        )
    finally:
        lock.release()
