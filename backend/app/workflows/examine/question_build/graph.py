"""LangGraph definition and public runtime entrypoint for exam question build."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.examine.question_build.nodes import (
    build_assign_question_weights_node,
    build_generate_questions_node,
    build_plan_question_blueprints_node,
)
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
        "plan_question_blueprints",
        trace.node(
            build_plan_question_blueprints_node(context=context or create_langgraph_dev_context(workflow_name)),
            name="plan_question_blueprints",
            timing_field="plan_ms",
        ),
    )
    workflow.add_node(
        "generate_questions",
        trace.node(
            build_generate_questions_node(context=context or create_langgraph_dev_context(workflow_name)),
            name="generate_questions",
            timing_field="generate_ms",
        ),
    )
    workflow.add_node(
        "assign_question_weights",
        trace.node(
            build_assign_question_weights_node(context=context or create_langgraph_dev_context(workflow_name)),
            name="assign_question_weights",
            timing_field="weight_ms",
        ),
    )
    workflow.set_entry_point("plan_question_blueprints")
    workflow.add_edge("plan_question_blueprints", "generate_questions")
    workflow.add_edge("generate_questions", "assign_question_weights")
    workflow.add_edge("assign_question_weights", END)
    return workflow


def get_langgraph_dev_question_build_graph() -> StateGraph:
    return build_question_build_graph(
        context=create_langgraph_dev_context("examine.question_build.langgraph_dev"),
    )


def create_question_build_initial_state(
    *,
    subject: str,
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    exam_mode: str = "web_practice",
    subject_context: str = "",
    focus_prompt: str = "",
    user_prompt: str = "",
    style_prompt: str = "",
    units: list | None = None,
    specs: list | None = None,
    question_count: int | None = None,
    requested_difficulty: str = "medium",
    mastery_by_unit_id: dict[int, float] | None = None,
    progress_callback: object | None = None,
) -> QuestionBuildState:
    return {
        "subject": subject,
        "subject_name": subject_name,
        "subject_description": subject_description,
        "subject_user_intent": subject_user_intent,
        "exam_mode": exam_mode,
        "subject_context": subject_context,
        "focus_prompt": focus_prompt,
        "user_prompt": user_prompt,
        "style_prompt": style_prompt,
        "units": list(units or []),
        "specs": list(specs or []),
        "question_count": int(question_count or len(specs or []) or len(units or []) or 1),
        "requested_difficulty": requested_difficulty,
        "mastery_by_unit_id": dict(mastery_by_unit_id or {}),
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
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    exam_mode: str = "web_practice",
    subject_context: str = "",
    focus_prompt: str = "",
    user_prompt: str = "",
    style_prompt: str = "",
    units: list | None = None,
    specs: list | None = None,
    question_count: int | None = None,
    requested_difficulty: str = "medium",
    mastery_by_unit_id: dict[int, float] | None = None,
    progress_callback: object | None = None,
) -> WorkflowResult[QuestionBuildState]:
    context = WorkflowContext(
        workflow_name="examine.question_build",
        subject=subject,
        metadata={
            "lane": "question_build",
            "langsmith_run_name": RUN_NAME_EXAM_QUESTION_BUILD,
            "question_count": int(question_count or len(specs or []) or len(units or []) or 1),
            "exam_mode": exam_mode,
        },
    )
    return await run_state_graph(
        workflow_name="examine.question_build",
        graph_builder=lambda: build_question_build_graph(context=context),
        initial_state=create_question_build_initial_state(
            subject=subject,
            subject_name=subject_name,
            subject_description=subject_description,
            subject_user_intent=subject_user_intent,
            exam_mode=exam_mode,
            subject_context=subject_context,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            style_prompt=style_prompt,
            units=list(units or []),
            specs=specs,
            question_count=question_count,
            requested_difficulty=requested_difficulty,
            mastery_by_unit_id=mastery_by_unit_id,
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
