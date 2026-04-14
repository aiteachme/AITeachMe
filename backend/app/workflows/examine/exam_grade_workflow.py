"""Exam grading workflow orchestration.
Reads DB: ``exam_paper*`` and downstream profile state tables.
Writes DB: ``exam_paper.status``, graded attempts,
``user_knowledge_state`` and ``review_task`` via delegated profile steps.
Writes FS: none.
Idempotency: reruns reconcile the same paper rather than creating parallel grading flows.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from typing import Generator

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.shared.infra.database import managed_session
from app.models import ExamPaper, ExamPaperStatus, validate_status_transition
from app.utils.time import utcnow
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.runtime import invoke_state_graph
from app.workflows.examine.answer_grader import grade_paper
from app.workflows.examine.state import ExamGradeState
from app.workflows.profile.mastery_updater import update_mastery_from_exam
from app.workflows.profile.review_scheduler import schedule_reviews

logger = structlog.get_logger()


def _workflow_logger(state: ExamGradeState) -> structlog.stdlib.BoundLogger:
    return logger.bind(
        exam_paper_id=state["exam_paper_id"],
        job_id=state["job_id"],
        subject=state.get("subject", ""),
    )


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def _resolve_exam_subject(
    exam_paper_id: int,
    *,
    session_override: Session | None = None,
) -> str:
    try:
        with _node_session(session_override) as session:
            paper = session.get(ExamPaper, exam_paper_id)
            return paper.subject if paper is not None else ""
    except Exception:
        return ""

async def grade_answers_node(
    state: ExamGradeState,
    *,
    session_override: Session | None = None,
) -> ExamGradeState:
    """Load the paper, switch it into grading, and persist answer grading."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            paper = session.get(ExamPaper, state["exam_paper_id"])
            if paper is None:
                return {**state, "error": f"exam_paper_not_found: {state['exam_paper_id']}"}

            if paper.status == ExamPaperStatus.SUBMITTED.value:
                validate_status_transition(ExamPaperStatus.SUBMITTED, ExamPaperStatus.GRADING)
                paper.status = ExamPaperStatus.GRADING.value
                paper.updated_at = utcnow()
                session.add(paper)
            elif paper.status != ExamPaperStatus.GRADING.value:
                return {**state, "error": f"illegal_paper_status_for_grading:{paper.status}"}

            session.commit()

            grade_result = await grade_paper(session, state["exam_paper_id"])
            workflow_logger.info(
                "exam_grade_answers_complete",
                correct_items=grade_result.correct_items,
                total_items=grade_result.total_items,
                score=grade_result.score,
            )
            return {**state, "grade_result": grade_result, "error": None}
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("exam_grade_answers_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"grade_answers_failed: {exc}"}


async def update_mastery_node(
    state: ExamGradeState,
    *,
    session_override: Session | None = None,
) -> ExamGradeState:
    """Apply mastery updates derived from the graded exam paper."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            mastery_result = update_mastery_from_exam(session, state["exam_paper_id"])
            workflow_logger.info(
                "exam_update_mastery_complete",
                states_updated=mastery_result.states_updated,
                already_consumed=mastery_result.already_consumed,
            )
            return {**state, "mastery_result": mastery_result, "error": None}
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("exam_update_mastery_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"update_mastery_failed: {exc}"}


async def schedule_reviews_node(
    state: ExamGradeState,
    *,
    session_override: Session | None = None,
) -> ExamGradeState:
    """Schedule follow-up review tasks for the updated knowledge states."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            paper = session.get(ExamPaper, state["exam_paper_id"])
            if paper is None:
                return {**state, "error": f"exam_paper_not_found: {state['exam_paper_id']}"}
            mastery_result = state.get("mastery_result")
            if mastery_result is None:
                return {**state, "error": "mastery_result_missing"}

            tasks = schedule_reviews(
                session,
                user_id=paper.user_id,
                subject=paper.subject,
                updated_state_ids=mastery_result.updated_state_ids,
            )
            task_ids = [item.id for item in tasks if item.id is not None]
            workflow_logger.info("exam_schedule_reviews_complete", task_count=len(task_ids))
            return {**state, "review_tasks": task_ids, "error": None}
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("exam_schedule_reviews_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"schedule_reviews_failed: {exc}"}


async def finalize_grade_node(
    state: ExamGradeState,
    *,
    session_override: Session | None = None,
) -> ExamGradeState:
    """Mark the paper graded and log the final grading summary."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            paper = session.get(ExamPaper, state["exam_paper_id"])
            if paper is None:
                return {**state, "error": f"exam_paper_not_found: {state['exam_paper_id']}"}

            if paper.status == ExamPaperStatus.GRADING.value:
                validate_status_transition(ExamPaperStatus.GRADING, ExamPaperStatus.GRADED)
                paper.status = ExamPaperStatus.GRADED.value
                paper.graded_at = paper.graded_at or utcnow()
                paper.updated_at = utcnow()
                session.add(paper)

            grade_result = state.get("grade_result")
            mastery_result = state.get("mastery_result")
            review_tasks = state.get("review_tasks", [])

            session.commit()

            workflow_logger.info(
                "exam_finalize_grade_complete",
                score=float(grade_result.score if grade_result is not None else 0.0),
                states_updated=int(mastery_result.states_updated if mastery_result is not None else 0),
                tasks_created=len(review_tasks),
            )
            return {**state, "error": None}
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("exam_finalize_grade_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"finalize_grade_failed: {exc}"}


async def fail_grade_node(
    state: ExamGradeState,
    *,
    session_override: Session | None = None,
) -> ExamGradeState:
    """Rollback the paper status when grading fails."""

    with _node_session(session_override) as session:
        workflow_logger = _workflow_logger(state)
        try:
            error_message = str(state.get("error", "unknown_error"))
            paper = session.get(ExamPaper, state["exam_paper_id"])
            if paper is not None and paper.status == ExamPaperStatus.GRADING.value:
                paper.status = ExamPaperStatus.SUBMITTED.value
                paper.updated_at = utcnow()
                session.add(paper)
            session.commit()

            workflow_logger.error("exam_grade_failed", error=error_message)
            return state
        except Exception as exc:  # noqa: BLE001
            workflow_logger.error("exam_grade_fail_node_error", error=str(exc), exc_info=True)
            return state


def _route_after_step(state: ExamGradeState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def build_exam_grade_graph(*, session: Session | None = None) -> StateGraph:
    workflow = StateGraph(ExamGradeState)
    trace = workflow_tracer(workflow="examine.exam_grade", lane="exam_grade")
    workflow.add_node(
        "grade_answers",
        trace.node(
            partial(grade_answers_node, session_override=session),
            name="grade_answers",
        ),
    )
    workflow.add_node(
        "update_mastery",
        trace.node(
            partial(update_mastery_node, session_override=session),
            name="update_mastery",
        ),
    )
    workflow.add_node(
        "schedule_reviews",
        trace.node(
            partial(schedule_reviews_node, session_override=session),
            name="schedule_reviews",
        ),
    )
    workflow.add_node(
        "finalize_grade",
        trace.node(
            partial(finalize_grade_node, session_override=session),
            name="finalize_grade",
        ),
    )
    workflow.add_node(
        "fail_grade",
        trace.node(
            partial(fail_grade_node, session_override=session),
            name="fail_grade",
        ),
    )

    workflow.set_entry_point("grade_answers")
    workflow.add_conditional_edges(
        "grade_answers",
        _route_after_step,
        {"continue": "update_mastery", "fail": "fail_grade"},
    )
    workflow.add_conditional_edges(
        "update_mastery",
        _route_after_step,
        {"continue": "schedule_reviews", "fail": "fail_grade"},
    )
    workflow.add_conditional_edges(
        "schedule_reviews",
        _route_after_step,
        {"continue": "finalize_grade", "fail": "fail_grade"},
    )
    workflow.add_edge("finalize_grade", END)
    workflow.add_edge("fail_grade", END)
    return workflow

async def run_exam_grade_workflow(
    *,
    exam_paper_id: int,
    job_id: int,
    session: Session | None = None,
) -> ExamGradeState:
    subject = _resolve_exam_subject(exam_paper_id, session_override=session)
    initial_state: ExamGradeState = {
        "exam_paper_id": exam_paper_id,
        "job_id": job_id,
        "subject": subject,
        "grade_result": None,
        "mastery_result": None,
        "review_tasks": [],
        "error": None,
    }
    return await invoke_state_graph(
        workflow_name="examine.exam_grade",
        graph_builder=lambda: build_exam_grade_graph(session=session),
        initial_state=initial_state,
        subject=subject,
        build_session_id=str(job_id),
        lane="exam_grade",
        extra_metadata={
            "job_id": job_id,
            "exam_paper_id": exam_paper_id,
        },
    )


class ExamGradeWorkflow:
    """Thin wrapper around the exam grading workflow."""

    @staticmethod
    def build_graph(*, session: Session | None = None) -> StateGraph:
        return build_exam_grade_graph(session=session)

    @staticmethod
    async def run(
        *,
        exam_paper_id: int,
        job_id: int,
        session: Session | None = None,
    ) -> ExamGradeState:
        return await run_exam_grade_workflow(
            exam_paper_id=exam_paper_id,
            job_id=job_id,
            session=session,
        )

