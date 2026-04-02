"""Question build workflow based on LangGraph.

Reads DB: teaching units and graph-backed teaching context.
Writes DB: question_template via downstream builder.
Writes FS: none.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from typing import Generator

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session, select

from app.infra.database import managed_session
from app.infra.tracing import llm_trace_scope
from app.models import QuestionTemplate
from app.repositories.knowledge import curriculum_repo, kg_repo
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
    """Load valid teaching units with revision/member context."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            source_unit_ids = state.get("unit_ids") or []
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
    """Generate templates for all units in one parallel batch."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            unit_ids = state.get("unit_ids", [])
            warnings = list(state.get("warnings", []))
            questions_per_unit = int(state.get("questions_per_unit", 1))

            with llm_trace_scope(
                subject=state["subject"],
                build_session_id=str(state["job_id"]),
                workflow="examine.question_build",
                lane="question_build",
                node="generate_templates",
            ):
                templates = await build_question_templates(
                    session,
                    subject=state["subject"],
                    user_id=state.get("user_id", "local"),
                    unit_ids=unit_ids,
                    questions_per_unit=questions_per_unit,
                    exam_mode=state.get("exam_mode", "diagnostic"),
                    preferred_question_types=list(state.get("preferred_question_types", [])),
                    user_prompt=state.get("user_prompt"),
                    focus_prompt=state.get("focus_prompt"),
                    style_profile=state.get("style_profile"),
                )
            created_template_ids = [item.id for item in templates if item.id is not None]
            if not templates:
                warnings.append("batch_generated_zero_templates")

            workflow_logger.info(
                "question_build_generate_complete",
                unit_count=len(unit_ids),
                templates_created=len(created_template_ids),
                warning_count=len(warnings),
            )
            return {
                **state,
                "templates_created": len(created_template_ids),
                "warnings": warnings,
                "created_template_ids": sorted(set(int(item) for item in created_template_ids)),
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
    """Finalize question build state."""

    with _node_session(session_override):
        workflow_logger = _workflow_logger(state)
        try:
            workflow_logger.info(
                "question_build_finalize_complete",
                templates_created=int(state.get("templates_created", 0)),
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
    """Failure handler: cleanup templates created by current runtime job id."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            error_message = state.get("error", "unknown_error")
            template_ids = [
                int(item) for item in state.get("created_template_ids", []) if item is not None
            ]

            created_templates: list[QuestionTemplate] = []
            if template_ids:
                created_templates = list(
                    session.exec(
                        select(QuestionTemplate).where(
                            QuestionTemplate.id.in_(template_ids)  # type: ignore[union-attr]
                        )
                    ).all()
                )
                for template in created_templates:
                    session.delete(template)
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
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int,
    job_id: int,
    exam_mode: str = "diagnostic",
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile=None,
    session: Session | None = None,
) -> QuestionBuildState:
    graph = build_question_build_graph(session=session)
    app = graph.compile()
    initial_state: QuestionBuildState = {
        "subject": subject,
        "user_id": user_id,
        "unit_ids": unit_ids,
        "questions_per_unit": questions_per_unit,
        "job_id": job_id,
        "exam_mode": exam_mode,
        "preferred_question_types": preferred_question_types or [],
        "user_prompt": user_prompt,
        "focus_prompt": focus_prompt,
        "style_profile": style_profile,
        "templates_created": 0,
        "warnings": [],
        "error": None,
        "created_template_ids": [],
    }
    result = await app.ainvoke(initial_state)
    return result


class QuestionBuildWorkflow:
    """Service-layer wrapper."""

    @staticmethod
    def build_graph(*, session: Session | None = None) -> StateGraph:
        return build_question_build_graph(session=session)

    @staticmethod
    async def run(
        *,
        subject: str,
        user_id: str,
        unit_ids: list[int],
        questions_per_unit: int,
        job_id: int,
        exam_mode: str = "diagnostic",
        preferred_question_types: list[str] | None = None,
        user_prompt: str | None = None,
        focus_prompt: str | None = None,
        style_profile=None,
        session: Session | None = None,
    ) -> QuestionBuildState:
        return await run_question_build_workflow(
            subject=subject,
            user_id=user_id,
            unit_ids=unit_ids,
            questions_per_unit=questions_per_unit,
            job_id=job_id,
            exam_mode=exam_mode,
            preferred_question_types=preferred_question_types,
            user_prompt=user_prompt,
            focus_prompt=focus_prompt,
            style_profile=style_profile,
            session=session,
        )
