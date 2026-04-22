"""LangGraph definition and runtime entrypoints for exam grading workflows."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.models import ExamPaperItem
from app.schemas.exams import ExamStudyGuideResponse
from app.shared.infra.workflow import WorkflowContext, emit_progress, run_state_graph, workflow_tracer
from app.shared.infra.workflow.context import create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.workflows.examine.exam_grade.lib import (
    ExamItemGradeDecision,
    generate_exam_study_guide,
    grade_exam_items_with_workflow,
)

RUN_NAME_EXAM_GRADE = "考试引擎：判题工作流"
RUN_NAME_EXAM_STUDY_GUIDE = "考试引擎：学习指南"


class ExamGradeState(TypedDict, total=False):
    mode: Literal["grade_exam", "study_guide"]
    subject: str
    exam_paper_id: int
    items: list[ExamPaperItem]
    grade_decisions: list[ExamItemGradeDecision]
    exam_title: str
    score_summary: str
    wrong_question_summaries: list[dict[str, Any]]
    weak_points: list[dict[str, Any]]
    pending_reviews: list[dict[str, Any]]
    generated_at: datetime
    study_guide: ExamStudyGuideResponse
    progress_callback: object | None
    error: str


def build_exam_grade_graph(*, context: WorkflowContext | None = None) -> StateGraph:
    workflow_name = context.workflow_name if context is not None else "examine.exam_grade"
    workflow = StateGraph(ExamGradeState)
    trace = workflow_tracer(context=context, workflow=workflow_name, lane="exam_grade")
    workflow.add_node(
        "grade_exam",
        trace.node(_grade_exam_node, name="grade_exam", timing_field="grade_exam_ms"),
    )
    workflow.add_node(
        "generate_study_guide",
        trace.node(
            _generate_study_guide_node,
            name="generate_study_guide",
            timing_field="study_guide_ms",
        ),
    )
    workflow.add_conditional_edges(
        START,
        _route_by_mode,
        {
            "grade_exam": "grade_exam",
            "study_guide": "generate_study_guide",
        },
    )
    workflow.add_edge("grade_exam", END)
    workflow.add_edge("generate_study_guide", END)
    return workflow


def _route_by_mode(state: ExamGradeState) -> str:
    mode = str(state.get("mode") or "").strip()
    if mode == "study_guide":
        return "study_guide"
    return "grade_exam"


async def _grade_exam_node(state: ExamGradeState) -> ExamGradeState:
    started_at = perf_counter()
    await emit_progress(
        state,
        stage="grade_exam",
        detail="正在批改试卷并生成逐题解析...",
        step="grade_exam",
    )
    decisions = await grade_exam_items_with_workflow(
        subject=str(state.get("subject") or ""),
        items=list(state.get("items") or []),
    )
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    await emit_progress(
        state,
        stage="grade_exam",
        detail="试卷批改完成。",
        step="grade_exam",
        elapsed_ms=elapsed_ms,
    )
    return {
        **state,
        "grade_decisions": decisions,
        "error": "",
    }


async def _generate_study_guide_node(state: ExamGradeState) -> ExamGradeState:
    started_at = perf_counter()
    await emit_progress(
        state,
        stage="study_guide",
        detail="正在整理错题薄弱点并生成学习指南...",
        step="generate_study_guide",
    )
    study_guide = await generate_exam_study_guide(
        exam_paper_id=int(state.get("exam_paper_id") or 0),
        subject=str(state.get("subject") or ""),
        exam_title=str(state.get("exam_title") or ""),
        score_summary=str(state.get("score_summary") or ""),
        wrong_question_summaries=list(state.get("wrong_question_summaries") or []),
        weak_points=list(state.get("weak_points") or []),
        pending_reviews=list(state.get("pending_reviews") or []),
        generated_at=state.get("generated_at") or datetime.now(),
    )
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    await emit_progress(
        state,
        stage="study_guide",
        detail="学习指南已生成。",
        step="generate_study_guide",
        elapsed_ms=elapsed_ms,
    )
    return {
        **state,
        "study_guide": study_guide,
        "error": "",
    }


def _create_grade_initial_state(
    *,
    subject: str,
    items: list[ExamPaperItem],
    progress_callback: object | None = None,
) -> ExamGradeState:
    return {
        "mode": "grade_exam",
        "subject": subject,
        "items": list(items),
        "progress_callback": progress_callback,
        "error": "",
    }


def _create_study_guide_initial_state(
    *,
    exam_paper_id: int,
    subject: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, Any]],
    weak_points: list[dict[str, Any]],
    pending_reviews: list[dict[str, Any]],
    generated_at: datetime,
    progress_callback: object | None = None,
) -> ExamGradeState:
    return {
        "mode": "study_guide",
        "exam_paper_id": exam_paper_id,
        "subject": subject,
        "exam_title": exam_title,
        "score_summary": score_summary,
        "wrong_question_summaries": list(wrong_question_summaries),
        "weak_points": list(weak_points),
        "pending_reviews": list(pending_reviews),
        "generated_at": generated_at,
        "progress_callback": progress_callback,
        "error": "",
    }


def _require_success_state(result: WorkflowResult[ExamGradeState]) -> ExamGradeState:
    state = result.require_value()
    error = str(state.get("error") or "").strip()
    if error:
        raise WorkflowError(code="exam_grade_failed", detail=error)
    return state


def get_langgraph_dev_exam_grade_graph() -> StateGraph:
    return build_exam_grade_graph(
        context=create_langgraph_dev_context("examine.exam_grade.langgraph_dev"),
    )


async def run_exam_grade_workflow(
    *,
    subject: str,
    items: list[ExamPaperItem],
    progress_callback: object | None = None,
) -> list[ExamItemGradeDecision]:
    """Run the production exam grading workflow."""

    context = WorkflowContext(
        workflow_name="examine.exam_grade",
        subject=subject,
        metadata={
            "lane": "exam_grade",
            "langsmith_run_name": RUN_NAME_EXAM_GRADE,
            "exam_item_count": len(items),
            "mode": "grade_exam",
        },
    )
    result = await run_state_graph(
        workflow_name="examine.exam_grade",
        graph_builder=lambda: build_exam_grade_graph(context=context),
        initial_state=_create_grade_initial_state(
            subject=subject,
            items=items,
            progress_callback=progress_callback,
        ),
        context=context,
    )
    state = _require_success_state(result)
    return list(state.get("grade_decisions") or [])


async def run_exam_study_guide_workflow(
    *,
    exam_paper_id: int,
    subject: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, Any]],
    weak_points: list[dict[str, Any]],
    pending_reviews: list[dict[str, Any]],
    generated_at: datetime,
    progress_callback: object | None = None,
) -> ExamStudyGuideResponse:
    """Run the production exam study-guide workflow."""

    context = WorkflowContext(
        workflow_name="examine.exam_grade",
        subject=subject,
        metadata={
            "lane": "exam_grade",
            "langsmith_run_name": RUN_NAME_EXAM_STUDY_GUIDE,
            "exam_paper_id": exam_paper_id,
            "mode": "study_guide",
        },
    )
    result = await run_state_graph(
        workflow_name="examine.exam_grade",
        graph_builder=lambda: build_exam_grade_graph(context=context),
        initial_state=_create_study_guide_initial_state(
            exam_paper_id=exam_paper_id,
            subject=subject,
            exam_title=exam_title,
            score_summary=score_summary,
            wrong_question_summaries=wrong_question_summaries,
            weak_points=weak_points,
            pending_reviews=pending_reviews,
            generated_at=generated_at,
            progress_callback=progress_callback,
        ),
        context=context,
    )
    state = _require_success_state(result)
    study_guide = state.get("study_guide")
    if study_guide is None:
        raise WorkflowError(code="exam_study_guide_failed", detail="study_guide_missing")
    return study_guide


__all__ = [
    "ExamGradeState",
    "RUN_NAME_EXAM_GRADE",
    "RUN_NAME_EXAM_STUDY_GUIDE",
    "build_exam_grade_graph",
    "get_langgraph_dev_exam_grade_graph",
    "run_exam_grade_workflow",
    "run_exam_study_guide_workflow",
]
