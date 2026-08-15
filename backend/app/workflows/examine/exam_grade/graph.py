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
_UNKNOWN_COURSE_NAME = "未命名课程"

NODE_GRADE_EXAM = "grade_exam"
NODE_GENERATE_STUDY_GUIDE = "generate_study_guide"

NODE_DISPLAY_NAMES = {
    NODE_GRADE_EXAM: "批改试卷",
    NODE_GENERATE_STUDY_GUIDE: "生成学习指南",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_GRADE_EXAM: {
        "description": (
            "批改整张试卷：客观题先用规则判定，再调用 LLM 生成个性化反馈；"
            "主观题调用结构化判分模型，并保留兜底评分路径。"
        ),
        "reads": ["ExamPaperItem snapshots", "answer_content", "LLM provider"],
        "writes": ["grade_decisions"],
        "emits": ["progress:grade_exam"],
        "input_keys": ["mode", "course_id", "course_name", "items"],
        "output_keys": ["grade_decisions", "grade_exam_ms", "error"],
    },
    NODE_GENERATE_STUDY_GUIDE: {
        "description": (
            "根据已评分试卷的错题摘要、本卷知识点表现、累计画像上下文和待复习项生成学习指南；"
            "该节点不重新判卷，只把诊断结果转成下一步学习建议。"
        ),
        "reads": ["exam score summary", "wrong_question_summaries", "knowledge_unit_performance", "pending_reviews", "LLM provider"],
        "writes": ["study_guide"],
        "emits": ["progress:study_guide"],
        "input_keys": [
            "mode",
            "exam_paper_id",
            "course_id",
            "course_name",
            "exam_title",
            "score_summary",
            "wrong_question_summaries",
            "knowledge_unit_performance",
            "pending_reviews",
            "generated_at",
        ],
        "output_keys": ["study_guide", "study_guide_ms", "error"],
    },
}


class ExamGradeState(TypedDict, total=False):
    mode: Literal["grade_exam", "study_guide"]
    course_id: str
    course_name: str
    exam_paper_id: int
    items: list[ExamPaperItem]
    grade_decisions: list[ExamItemGradeDecision]
    exam_title: str
    score_summary: str
    wrong_question_summaries: list[dict[str, Any]]
    knowledge_unit_performance: list[dict[str, Any]]
    pending_reviews: list[dict[str, Any]]
    generated_at: datetime
    study_guide: ExamStudyGuideResponse
    progress_callback: object | None
    content_callback: object | None
    error: str


def build_exam_grade_graph(*, context: WorkflowContext | None = None) -> StateGraph:
    workflow_name = context.workflow_name if context is not None else "examine.exam_grade"
    workflow = StateGraph(ExamGradeState)
    trace = workflow_tracer(context=context, workflow=workflow_name, lane="exam_grade")
    workflow.add_node(
        NODE_GRADE_EXAM,
        _trace_exam_grade_node(
            trace,
            NODE_GRADE_EXAM,
            _grade_exam_node,
            timing_field="grade_exam_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_GRADE_EXAM),
    )
    workflow.add_node(
        NODE_GENERATE_STUDY_GUIDE,
        _trace_exam_grade_node(
            trace,
            NODE_GENERATE_STUDY_GUIDE,
            _generate_study_guide_node,
            timing_field="study_guide_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_GENERATE_STUDY_GUIDE),
    )
    workflow.add_conditional_edges(
        START,
        ROUTE_BY_MODE,
        {
            "grade_exam": NODE_GRADE_EXAM,
            "study_guide": NODE_GENERATE_STUDY_GUIDE,
        },
    )
    workflow.add_edge(NODE_GRADE_EXAM, END)
    workflow.add_edge(NODE_GENERATE_STUDY_GUIDE, END)
    return workflow


def _trace_exam_grade_node(trace, node_key: str, handler, *, timing_field: str):
    details = NODE_TRACE_DETAILS[node_key]
    return trace.node(
        handler,
        name=node_key,
        display_name=NODE_DISPLAY_NAMES[node_key],
        description=str(details["description"]),
        timing_field=timing_field,
        input_keys=list(details["input_keys"]),
        output_keys=list(details["output_keys"]),
        metadata=_langgraph_node_metadata(node_key),
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    details = NODE_TRACE_DETAILS[node_key]
    return {
        "node_key": node_key,
        "node_display_name": NODE_DISPLAY_NAMES[node_key],
        "node_description": details["description"],
        "reads": list(details["reads"]),
        "writes": list(details["writes"]),
        "emits": list(details["emits"]),
        "state_inputs": list(details["input_keys"]),
        "state_outputs": list(details["output_keys"]),
    }


def _route_by_mode(state: ExamGradeState) -> str:
    mode = str(state.get("mode") or "").strip()
    if mode == "study_guide":
        return "study_guide"
    return "grade_exam"


def _named_route(fn, name: str):
    fn.__name__ = name
    fn.__qualname__ = name
    return fn


ROUTE_BY_MODE = _named_route(_route_by_mode, "按模式选择判题或学习指南")


def _state_course_name(state: ExamGradeState) -> str:
    return str(state.get("course_name") or "").strip() or _UNKNOWN_COURSE_NAME


async def _grade_exam_node(state: ExamGradeState) -> ExamGradeState:
    started_at = perf_counter()
    await emit_progress(
        state,
        stage="grade_exam",
        detail="正在批改试卷并生成逐题解析...",
        step="grade_exam",
    )
    decisions = await grade_exam_items_with_workflow(
        course_name=_state_course_name(state),
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
        course_name=_state_course_name(state),
        exam_title=str(state.get("exam_title") or ""),
        score_summary=str(state.get("score_summary") or ""),
        wrong_question_summaries=list(state.get("wrong_question_summaries") or []),
        knowledge_unit_performance=list(state.get("knowledge_unit_performance") or []),
        pending_reviews=list(state.get("pending_reviews") or []),
        generated_at=state.get("generated_at") or datetime.now(),
        content_callback=state.get("content_callback"),
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
    course_id: str,
    course_name: str,
    items: list[ExamPaperItem],
    progress_callback: object | None = None,
) -> ExamGradeState:
    return {
        "mode": "grade_exam",
        "course_id": course_id,
        "course_name": course_name,
        "items": list(items),
        "progress_callback": progress_callback,
        "error": "",
    }


def _create_study_guide_initial_state(
    *,
    exam_paper_id: int,
    course_id: str,
    course_name: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, Any]],
    knowledge_unit_performance: list[dict[str, Any]],
    pending_reviews: list[dict[str, Any]],
    generated_at: datetime,
    progress_callback: object | None = None,
    content_callback: object | None = None,
) -> ExamGradeState:
    return {
        "mode": "study_guide",
        "exam_paper_id": exam_paper_id,
        "course_id": course_id,
        "course_name": course_name,
        "exam_title": exam_title,
        "score_summary": score_summary,
        "wrong_question_summaries": list(wrong_question_summaries),
        "knowledge_unit_performance": list(knowledge_unit_performance),
        "pending_reviews": list(pending_reviews),
        "generated_at": generated_at,
        "progress_callback": progress_callback,
        "content_callback": content_callback,
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
    course_id: str,
    course_name: str = "",
    items: list[ExamPaperItem],
    progress_callback: object | None = None,
) -> list[ExamItemGradeDecision]:
    """Run the production exam grading workflow."""

    context = WorkflowContext(
        workflow_name="examine.exam_grade",
        course_id=course_id,
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
            course_id=course_id,
            course_name=course_name or _UNKNOWN_COURSE_NAME,
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
    course_id: str,
    course_name: str = "",
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, Any]],
    knowledge_unit_performance: list[dict[str, Any]],
    pending_reviews: list[dict[str, Any]],
    generated_at: datetime,
    progress_callback: object | None = None,
    content_callback: object | None = None,
) -> ExamStudyGuideResponse:
    """Run the production exam study-guide workflow."""

    context = WorkflowContext(
        workflow_name="examine.exam_grade",
        course_id=course_id,
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
            course_id=course_id,
            course_name=course_name or _UNKNOWN_COURSE_NAME,
            exam_title=exam_title,
            score_summary=score_summary,
            wrong_question_summaries=wrong_question_summaries,
            knowledge_unit_performance=knowledge_unit_performance,
            pending_reviews=pending_reviews,
            generated_at=generated_at,
            progress_callback=progress_callback,
            content_callback=content_callback,
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
