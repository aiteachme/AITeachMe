"""QuestionBuildJob 工作流：基于 LangGraph 的题目模板构建状态机。

Reads DB: ``question_build_job``, ``teaching_unit*`` and graph-backed teaching context.
Writes DB: ``question_build_job`` progress/status and, via downstream builder calls,
``question_template`` / ``question_template_node_link``.
Writes FS: none.
Idempotency: reruns target the same build job and reuse its unit scope while refreshing progress.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from functools import partial
from typing import Generator

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session, select

from app.core.database import managed_session
from app.models import QuestionBuildJob, QuestionTemplate, QuestionTemplateNodeLink
from app.repositories.knowledge import curriculum_repo, kg_repo
from app.utils.time import utcnow
from app.workflows.examine.question_builder import build_question_templates
from app.workflows.examine.state import QuestionBuildState

logger = structlog.get_logger()


def _workflow_logger(state: QuestionBuildState) -> structlog.stdlib.BoundLogger:
    return logger.bind(
        subject=state["subject"],
        job_id=state["job_id"],
        unit_ids=state.get("unit_ids", []),
    )


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


async def load_units_node(
    state: QuestionBuildState,
    *,
    session_override: Session | None = None,
) -> QuestionBuildState:
    """加载可用教学单元（存在有效成员节点与修订）。"""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            job = session.get(QuestionBuildJob, state["job_id"])
            if job is None:
                return {**state, "error": f"question_build_job_not_found: {state['job_id']}"}

            if job.status == "pending":
                job.status = "running"
            job.progress = max(job.progress, 5)
            job.updated_at = utcnow()
            session.add(job)
            session.commit()

            source_unit_ids = state.get("unit_ids") or json.loads(job.target_unit_ids_json or "[]")
            warnings = list(state.get("warnings", []))
            valid_unit_ids: list[int] = []

            for unit_id in source_unit_ids:
                unit = curriculum_repo.get_teaching_unit_by_id(session, int(unit_id))
                if unit is None:
                    warnings.append(f"unit_not_found:{unit_id}")
                    continue
                if unit.subject != state["subject"]:
                    warnings.append(f"unit_subject_mismatch:{unit_id}")
                    continue

                memberships = curriculum_repo.list_memberships_by_unit(session, unit.id or int(unit_id))
                if not memberships:
                    warnings.append(f"unit_without_memberships:{unit_id}")
                    continue

                has_node_context = any(
                    kg_repo.get_node_with_current_revision(session, membership.knowledge_node_id) is not None
                    for membership in memberships
                )
                if not has_node_context:
                    warnings.append(f"unit_without_node_context:{unit_id}")
                    continue

                valid_unit_ids.append(int(unit_id))

            job.warnings_json = json.dumps(warnings, ensure_ascii=False)
            job.progress = max(job.progress, 10)
            job.updated_at = utcnow()
            session.add(job)
            session.commit()

            if not valid_unit_ids:
                workflow_logger.warning("question_build_load_units_no_valid_units")
                return {
                    **state,
                    "warnings": warnings,
                    "unit_ids": [],
                    "error": "no_valid_units",
                }

            workflow_logger.info("question_build_load_units_complete", valid_units=len(valid_unit_ids))
            return {
                **state,
                "unit_ids": valid_unit_ids,
                "warnings": warnings,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("question_build_load_units_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"load_units_failed: {exc}"}


async def generate_templates_node(
    state: QuestionBuildState,
    *,
    session_override: Session | None = None,
) -> QuestionBuildState:
    """逐单元调用 question_builder，单元失败时跳过并记录 warning。"""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            job = session.get(QuestionBuildJob, state["job_id"])
            if job is None:
                return {**state, "error": f"question_build_job_not_found: {state['job_id']}"}

            unit_ids = state.get("unit_ids", [])
            warnings = list(state.get("warnings", []))
            created_template_ids: list[int] = list(state.get("created_template_ids", []))
            templates_created = int(state.get("templates_created", 0))
            questions_per_unit = int(state.get("questions_per_unit", job.questions_per_unit))

            total_units = max(1, len(unit_ids))
            for idx, unit_id in enumerate(unit_ids, start=1):
                try:
                    templates = await build_question_templates(
                        session,
                        subject=state["subject"],
                        unit_ids=[unit_id],
                        questions_per_unit=questions_per_unit,
                        created_by_job_id=state["job_id"],
                    )
                    templates_created += len(templates)
                    created_template_ids.extend([item.id for item in templates if item.id is not None])
                    if not templates:
                        warnings.append(f"unit_generated_zero_templates:{unit_id}")
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"unit_generate_failed:{unit_id}:{exc}")
                    workflow_logger.warning(
                        "question_build_unit_generate_failed",
                        unit_id=unit_id,
                        error=str(exc),
                    )

                progress = 10 + int(80 * idx / total_units)
                job.progress = max(job.progress, min(progress, 90))
                job.templates_created = templates_created
                job.warnings_json = json.dumps(warnings, ensure_ascii=False)
                job.updated_at = utcnow()
                session.add(job)
                session.commit()

            workflow_logger.info(
                "question_build_generate_complete",
                unit_count=len(unit_ids),
                templates_created=templates_created,
                warning_count=len(warnings),
            )
            return {
                **state,
                "templates_created": templates_created,
                "warnings": warnings,
                "created_template_ids": sorted(set(created_template_ids)),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("question_build_generate_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"generate_templates_failed: {exc}"}


async def finalize_build_node(
    state: QuestionBuildState,
    *,
    session_override: Session | None = None,
) -> QuestionBuildState:
    """完成 QuestionBuildJob。"""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            job = session.get(QuestionBuildJob, state["job_id"])
            if job is None:
                return {**state, "error": f"question_build_job_not_found: {state['job_id']}"}

            job.status = "completed"
            job.progress = 100
            job.templates_created = int(state.get("templates_created", 0))
            job.warnings_json = json.dumps(state.get("warnings", []), ensure_ascii=False)
            job.error_message = None
            job.updated_at = utcnow()
            session.add(job)
            session.commit()
            session.refresh(job)

            workflow_logger.info(
                "question_build_finalize_complete",
                templates_created=job.templates_created,
                warning_count=len(state.get("warnings", [])),
            )
            return {**state, "error": None}
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("question_build_finalize_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"finalize_build_failed: {exc}"}


async def fail_build_node(
    state: QuestionBuildState,
    *,
    session_override: Session | None = None,
) -> QuestionBuildState:
    """失败处理：清理当前 job 产出的模板并标记 job 失败。"""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            job_id = state["job_id"]
            warnings = state.get("warnings", [])
            error_message = state.get("error", "unknown_error")

            created_templates = list(
                session.exec(
                    select(QuestionTemplate).where(QuestionTemplate.created_by_job_id == job_id)
                ).all()
            )
            template_ids = [item.id for item in created_templates if item.id is not None]
            if template_ids:
                links = list(
                    session.exec(
                        select(QuestionTemplateNodeLink).where(
                            QuestionTemplateNodeLink.question_template_id.in_(template_ids)  # type: ignore[union-attr]
                        )
                    ).all()
                )
                for link in links:
                    session.delete(link)
                for template in created_templates:
                    session.delete(template)

            job = session.get(QuestionBuildJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(error_message)
                job.warnings_json = json.dumps(warnings, ensure_ascii=False)
                job.updated_at = utcnow()
                session.add(job)
            session.commit()

            workflow_logger.error(
                "question_build_failed",
                error=error_message,
                cleaned_template_count=len(created_templates),
            )
            return state
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("question_build_fail_node_error", error=str(exc), exc_info=True)
            return state


def _route_after_step(state: QuestionBuildState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def build_question_build_graph(*, session: Session | None = None) -> StateGraph:
    workflow = StateGraph(QuestionBuildState)
    workflow.add_node("load_units", partial(load_units_node, session_override=session))
    workflow.add_node("generate_templates", partial(generate_templates_node, session_override=session))
    workflow.add_node("finalize_build", partial(finalize_build_node, session_override=session))
    workflow.add_node("fail_build", partial(fail_build_node, session_override=session))

    workflow.set_entry_point("load_units")
    workflow.add_conditional_edges(
        "load_units",
        _route_after_step,
        {"continue": "generate_templates", "fail": "fail_build"},
    )
    workflow.add_conditional_edges(
        "generate_templates",
        _route_after_step,
        {"continue": "finalize_build", "fail": "fail_build"},
    )
    workflow.add_edge("finalize_build", END)
    workflow.add_edge("fail_build", END)
    return workflow


async def run_question_build_workflow(
    *,
    subject: str,
    unit_ids: list[int],
    questions_per_unit: int,
    job_id: int,
    session: Session | None = None,
) -> QuestionBuildState:
    graph = build_question_build_graph(session=session)
    app = graph.compile()
    initial_state: QuestionBuildState = {
        "subject": subject,
        "unit_ids": unit_ids,
        "questions_per_unit": questions_per_unit,
        "job_id": job_id,
        "templates_created": 0,
        "warnings": [],
        "error": None,
        "created_template_ids": [],
    }
    result = await app.ainvoke(initial_state)
    return result


class QuestionBuildWorkflow:
    """供服务层调用的轻量包装。"""

    @staticmethod
    def build_graph(*, session: Session | None = None) -> StateGraph:
        return build_question_build_graph(session=session)

    @staticmethod
    async def run(
        *,
        subject: str,
        unit_ids: list[int],
        questions_per_unit: int,
        job_id: int,
        session: Session | None = None,
    ) -> QuestionBuildState:
        return await run_question_build_workflow(
            subject=subject,
            unit_ids=unit_ids,
            questions_per_unit=questions_per_unit,
            job_id=job_id,
            session=session,
        )
