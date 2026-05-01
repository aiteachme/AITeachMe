"""LangGraph definition and public runtime entrypoint for exam question build."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.examine.question_build.nodes import (
    build_filter_knowledge_units_node,
    build_generate_questions_node,
    build_plan_question_requirements_node,
    build_allocate_knowledge_units_node,
)
from app.workflows.examine.question_build.state import (
    QuestionBuildGraphInput,
    QuestionBuildGraphOutput,
    QuestionBuildState,
)

RUN_NAME_EXAM_QUESTION_BUILD = "考试引擎：生成考题"

NODE_FILTER_KNOWLEDGE_UNITS = "filter_knowledge_units"
NODE_PLAN_QUESTION_REQUIREMENTS = "plan_question_requirements"
NODE_ALLOCATE_KNOWLEDGE_UNITS = "allocate_knowledge_units"
NODE_GENERATE_QUESTIONS = "generate_questions"

NODE_DISPLAY_NAMES = {
    NODE_FILTER_KNOWLEDGE_UNITS: "筛选候选知识点",
    NODE_PLAN_QUESTION_REQUIREMENTS: "规划题目要求",
    NODE_ALLOCATE_KNOWLEDGE_UNITS: "分配考查知识点",
    NODE_GENERATE_QUESTIONS: "生成结构化题目",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_FILTER_KNOWLEDGE_UNITS: {
        "description": (
            "基于用户范围、薄弱掌握度、优先知识点和知识图谱边，从候选 KnowledgeUnit 中筛出适合本轮组卷的紧凑集合。"
            "优先使用 LLM 图谱筛选，失败时让节点显式返回 error，避免后续用空知识点静默生成。"
        ),
        "reads": ["knowledge_unit candidates", "knowledge_graph_edges", "mastery_by_unit_id", "priority_unit_ids", "user_prompt"],
        "writes": ["units(filtered)", "candidate_unit_ids", "scope/filter diagnostics"],
        "emits": ["progress:filter_exam_units"],
        "input_keys": [
            "course_id",
            "course_name",
            "course_description",
            "course_user_intent",
            "exam_mode",
            "units",
            "knowledge_graph_edges",
            "question_count",
            "mastery_by_unit_id",
            "priority_unit_ids",
            "user_prompt",
            "system_constraints",
        ],
        "output_keys": [
            "units",
            "candidate_unit_ids",
            "candidate_unit_limit",
            "input_unit_count",
            "knowledge_graph_edge_count",
            "candidate_unit_count",
            "scope_include_terms",
            "scope_exclude_terms",
            "scope_strict",
            "filter_strategy",
            "filter_rationale",
            "filter_ms",
            "error",
        ],
    },
    NODE_PLAN_QUESTION_REQUIREMENTS: {
        "description": (
            "把全局 exam_mode、题量和用户提示拆成每一道题的题型、难度和生成约束，"
            "为后续知识点分配提供稳定的题目蓝图前置条件。"
        ),
        "reads": ["exam_mode", "question_count", "user_prompt"],
        "writes": ["question_requirement_plans", "question_requirement_rationale"],
        "emits": ["progress:plan_question_requirements"],
        "input_keys": ["exam_mode", "question_count", "user_prompt"],
        "output_keys": [
            "question_requirement_plans",
            "question_requirement_rationale",
            "requirements_plan_ms",
            "error",
        ],
    },
    NODE_ALLOCATE_KNOWLEDGE_UNITS: {
        "description": (
            "把筛选后的 KnowledgeUnit 与每题要求匹配成 ExamQuestionBlueprint，"
            "显式记录每题考查哪些知识点、题型和生成提示，后续生成节点只消费这些蓝图。"
        ),
        "reads": [
            "units(filtered)",
            "question_requirement_plans",
            "mastery_by_unit_id",
            "course profile",
            "system_constraints",
        ],
        "writes": ["question_blueprints"],
        "emits": ["progress:allocate_knowledge_units"],
        "input_keys": [
            "course_id",
            "course_name",
            "course_description",
            "course_user_intent",
            "exam_mode",
            "units",
            "question_count",
            "mastery_by_unit_id",
            "question_requirement_plans",
            "user_prompt",
            "system_constraints",
        ],
        "output_keys": ["question_blueprints", "allocate_ms", "error"],
    },
    NODE_GENERATE_QUESTIONS: {
        "description": (
            "按已冻结的 ExamQuestionBlueprint 并发生成结构化题目。每题失败会被记录到 failed_questions；"
            "当允许部分成功时，节点保留已生成题目并把失败详情交给调用方展示。"
        ),
        "reads": ["question_blueprints", "units(filtered)", "course profile", "system_constraints"],
        "writes": ["generated_questions", "failed_questions", "failed_question_count"],
        "emits": ["progress:generate_exam_questions", "progress:generate_question"],
        "input_keys": [
            "question_blueprints",
            "units",
            "course_name",
            "course_description",
            "course_user_intent",
            "system_constraints",
        ],
        "output_keys": [
            "generated_questions",
            "failed_questions",
            "failed_question_count",
            "generate_ms",
            "error",
        ],
    },
}


def build_question_build_graph(*, context: WorkflowContext | None = None) -> StateGraph:
    workflow_name = context.workflow_name if context is not None else "examine.question_build"
    workflow = StateGraph(
        QuestionBuildState,
        input_schema=QuestionBuildGraphInput,
        output_schema=QuestionBuildGraphOutput,
    )
    trace = workflow_tracer(context=context, workflow=workflow_name, lane="question_build")
    workflow.add_node(
        NODE_FILTER_KNOWLEDGE_UNITS,
        _trace_question_build_node(
            trace,
            NODE_FILTER_KNOWLEDGE_UNITS,
            build_filter_knowledge_units_node(context=context or create_langgraph_dev_context(workflow_name)),
            timing_field="filter_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_FILTER_KNOWLEDGE_UNITS),
    )
    workflow.add_node(
        NODE_PLAN_QUESTION_REQUIREMENTS,
        _trace_question_build_node(
            trace,
            NODE_PLAN_QUESTION_REQUIREMENTS,
            build_plan_question_requirements_node(context=context or create_langgraph_dev_context(workflow_name)),
            timing_field="requirements_plan_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_PLAN_QUESTION_REQUIREMENTS),
    )
    workflow.add_node(
        NODE_ALLOCATE_KNOWLEDGE_UNITS,
        _trace_question_build_node(
            trace,
            NODE_ALLOCATE_KNOWLEDGE_UNITS,
            build_allocate_knowledge_units_node(context=context or create_langgraph_dev_context(workflow_name)),
            timing_field="allocate_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_ALLOCATE_KNOWLEDGE_UNITS),
    )
    workflow.add_node(
        NODE_GENERATE_QUESTIONS,
        _trace_question_build_node(
            trace,
            NODE_GENERATE_QUESTIONS,
            build_generate_questions_node(context=context or create_langgraph_dev_context(workflow_name)),
            timing_field="generate_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_GENERATE_QUESTIONS),
    )
    workflow.set_entry_point(NODE_FILTER_KNOWLEDGE_UNITS)
    workflow.add_edge(NODE_FILTER_KNOWLEDGE_UNITS, NODE_PLAN_QUESTION_REQUIREMENTS)
    workflow.add_edge(NODE_PLAN_QUESTION_REQUIREMENTS, NODE_ALLOCATE_KNOWLEDGE_UNITS)
    workflow.add_edge(NODE_ALLOCATE_KNOWLEDGE_UNITS, NODE_GENERATE_QUESTIONS)
    workflow.add_edge(NODE_GENERATE_QUESTIONS, END)
    return workflow


def _trace_question_build_node(trace, node_key: str, handler, *, timing_field: str):
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


def get_langgraph_dev_question_build_graph() -> StateGraph:
    return build_question_build_graph(
        context=create_langgraph_dev_context("examine.question_build.langgraph_dev"),
    )


def create_question_build_initial_state(
    *,
    course_id: str,
    course_name: str = "",
    course_description: str = "",
    course_user_intent: str = "",
    exam_mode: str = "web_practice",
    course_context: str = "",
    user_prompt: str = "",
    system_constraints: str = "",
    units: list | None = None,
    knowledge_graph_edges: list[dict] | None = None,
    question_count: int | None = None,
    mastery_by_unit_id: dict[int, float] | None = None,
    priority_unit_ids: list[int] | None = None,
    progress_callback: object | None = None,
) -> QuestionBuildState:
    return {
        "course_id": course_id,
        "course_name": course_name,
        "course_description": course_description,
        "course_user_intent": course_user_intent,
        "exam_mode": exam_mode,
        "course_context": course_context,
        "user_prompt": user_prompt,
        "system_constraints": system_constraints,
        "units": list(units or []),
        "knowledge_graph_edges": list(knowledge_graph_edges or []),
        "question_count": int(question_count or len(units or []) or 1),
        "mastery_by_unit_id": dict(mastery_by_unit_id or {}),
        "priority_unit_ids": list(priority_unit_ids or []),
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
    course_id: str,
    course_name: str = "",
    course_description: str = "",
    course_user_intent: str = "",
    exam_mode: str = "web_practice",
    course_context: str = "",
    user_prompt: str = "",
    system_constraints: str = "",
    units: list | None = None,
    knowledge_graph_edges: list[dict] | None = None,
    question_count: int | None = None,
    mastery_by_unit_id: dict[int, float] | None = None,
    priority_unit_ids: list[int] | None = None,
    progress_callback: object | None = None,
) -> WorkflowResult[QuestionBuildState]:
    context = WorkflowContext(
        workflow_name="examine.question_build",
        course_id=course_id,
        metadata={
            "lane": "question_build",
            "langsmith_run_name": RUN_NAME_EXAM_QUESTION_BUILD,
            "question_count": int(question_count or len(units or []) or 1),
            "exam_mode": exam_mode,
        },
    )
    return await run_state_graph(
        workflow_name="examine.question_build",
        graph_builder=lambda: build_question_build_graph(context=context),
        initial_state=create_question_build_initial_state(
            course_id=course_id,
            course_name=course_name,
            course_description=course_description,
            course_user_intent=course_user_intent,
            exam_mode=exam_mode,
            course_context=course_context,
            user_prompt=user_prompt,
            system_constraints=system_constraints,
            units=list(units or []),
            knowledge_graph_edges=list(knowledge_graph_edges or []),
            question_count=question_count,
            mastery_by_unit_id=mastery_by_unit_id,
            priority_unit_ids=priority_unit_ids,
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
