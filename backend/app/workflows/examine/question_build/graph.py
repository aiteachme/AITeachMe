"""LangGraph definition and public runtime entrypoint for exam question build."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.examine.question_build.nodes import build_generate_questions_node
from app.workflows.examine.question_build.state import (
    QuestionBuildGraphInput,
    QuestionBuildGraphOutput,
    QuestionBuildState,
)

RUN_NAME_EXAM_QUESTION_BUILD = "考试引擎：生成考题"


def build_question_build_graph(*, context: WorkflowContext | None = None) -> StateGraph:
    workflow_name = context.workflow_name if context is not None else "examine.question_build"
    workflow = StateGraph(
        QuestionBuildState,
        input_schema=QuestionBuildGraphInput,
        output_schema=QuestionBuildGraphOutput,
    )
    trace = workflow_tracer(context=context, workflow=workflow_name, lane="question_build")
    workflow.add_node(
        "generate_questions",
        trace.node(
            build_generate_questions_node(context=context or create_langgraph_dev_context(workflow_name)),
            name="generate_questions",
            timing_field="generate_ms",
        ),
    )
    workflow.set_entry_point("generate_questions")
    workflow.add_edge("generate_questions", END)
    return workflow


def get_langgraph_dev_question_build_graph() -> StateGraph:
    return build_question_build_graph(
        context=create_langgraph_dev_context("examine.question_build.langgraph_dev"),
    )


def create_question_build_initial_state(
    *,
    subject: str,
    exam_mode: str,
    focus_prompt: str,
    user_prompt: str,
    style_prompt: str,
    units: list,
    specs: list,
    progress_callback: object | None = None,
) -> QuestionBuildState:
    return {
        "subject": subject,
        "exam_mode": exam_mode,
        "focus_prompt": focus_prompt,
        "user_prompt": user_prompt,
        "style_prompt": style_prompt,
        "units": list(units),
        "specs": list(specs),
        "progress_callback": progress_callback,
        "error": "",
    }


def require_success_state(result: WorkflowResult[QuestionBuildState]) -> QuestionBuildState:
    state = result.require_value()
    error = str(state.get("error") or "").strip()
    if error:
        raise WorkflowError(code="exam_question_build_failed", detail=error)
    return state


async def run_question_build_workflow(
    *,
    subject: str,
    exam_mode: str,
    focus_prompt: str,
    user_prompt: str,
    style_prompt: str,
    units: list,
    specs: list,
    progress_callback: object | None = None,
) -> WorkflowResult[QuestionBuildState]:
    context = WorkflowContext(
        workflow_name="examine.question_build",
        subject=subject,
        metadata={
            "lane": "question_build",
            "langsmith_run_name": RUN_NAME_EXAM_QUESTION_BUILD,
            "question_count": len(specs),
            "exam_mode": exam_mode,
        },
    )
    return await run_state_graph(
        workflow_name="examine.question_build",
        graph_builder=lambda: build_question_build_graph(context=context),
        initial_state=create_question_build_initial_state(
            subject=subject,
            exam_mode=exam_mode,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            style_prompt=style_prompt,
            units=units,
            specs=specs,
            progress_callback=progress_callback,
        ),
        context=context,
    )


__all__ = [
    "RUN_NAME_EXAM_QUESTION_BUILD",
    "QuestionBuildState",
    "build_question_build_graph",
    "create_question_build_initial_state",
    "get_langgraph_dev_question_build_graph",
    "require_success_state",
    "run_question_build_workflow",
]
