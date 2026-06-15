"""Planner graph definition and public workflow entrypoints.

真实链路主线：
读取输入 -> 首轮并行生成规划判断/资料边界 -> 二阶段并行生成课程身份和方案大纲 -> 保存。
调整链路会复用上一版规划判断和课程身份，只调用一次方案生成。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Mapping

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.models.course import Course
from app.schemas.knowledge import BuildPlannerCreateRequest, BuildPlannerMessageRequest, BuildPlannerSessionResponse
from app.shared.infra.llm_support.model_choices import (
    normalize_runtime_model_override,
    use_runtime_model_override,
)
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.node_tracing import named_route, node_metadata, traced_digest_node
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.store import (
    get_planner_adjust_click_context,
    mark_planner_session_cancelled,
    mark_planner_session_draft,
    mark_planner_session_failed,
    planner_session_response_from_state,
)
from app.workflows.digest.planner.lib.steps import (
    STEP_COMPOSE_PLAN,
    STEP_DISPLAY_NAMES,
    STEP_GENERATE_TITLE,
    STEP_LOAD_MATERIALS,
    STEP_SAVE_PLAN,
    STEP_UNDERSTAND_GOAL,
)
from app.workflows.digest.planner.lib.tracing import normalize_planner_operation, planner_trace_run_name
from app.workflows.digest.planner.nodes.collect_planner_context import build_collect_planner_context_node
from app.workflows.digest.planner.nodes.compose_planner_draft import build_compose_planner_draft_node
from app.workflows.digest.planner.nodes.generate_course_identity import build_generate_course_identity_node
from app.workflows.digest.planner.nodes.save_planner_draft import build_save_planner_draft_node
from app.workflows.digest.planner.nodes.understand_goal_and_materials import build_understand_goal_and_materials_node
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)

logger = structlog.get_logger(__name__)

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    STEP_LOAD_MATERIALS: {
        "description": (
            "把 API 请求整理成本轮 Planner 可用上下文：读取或创建 planner session，锁定选择的资料，"
            "加载可读 markdown / digest / 当前知识文档摘要。若资料还在解析，只用文件名、检测信息和用户目标构造 seed context，"
            "明确标记为临时方案输入。"
        ),
        "reads": ["planner_session", "raw_file", "parsed_markdown", "material_digest_cache", "latest_plan"],
        "writes": ["selected_file_ids", "material_context", "digest_mode", "planner_context_stats"],
        "input_keys": [
            "course_id",
            "user_id",
            "planner_operation",
            "requested_file_ids",
            "session_title",
            "feedback_message",
            "file_ids",
            "user_prompt",
            "digest_mode",
            "model_override",
            "planner_session_id",
            "message_history",
            "latest_plan",
        ],
        "output_keys": [
            "selected_file_ids",
            "planner_context_stats",
            "material_context",
            "digest_mode",
            "prepare_ms",
            "error",
        ],
    },
    STEP_UNDERSTAND_GOAL: {
        "description": (
            "首轮生成时并行完成两个理解动作：流式写出用户可见的规划判断，结构化整理资料边界与学科情况。"
            "调整已有方案时不重新理解范围，直接复用上一版 planning_note。"
        ),
        "reads": ["material_context", "user_prompt", "digest_mode", "message_history", "latest_plan", "feedback_message"],
        "writes": ["planning_note", "material_note"],
        "input_keys": [
            "course_id",
            "material_context",
            "user_prompt",
            "digest_mode",
            "message_history",
            "latest_plan",
            "feedback_message",
            "planner_session_id",
            "model_override",
        ],
        "output_keys": ["planning_note", "material_note", "bootstrap_ms", "error"],
        "fanout": "stream_planning_note + summarize_materials",
        "routing": "after this node, LangGraph runs compose_plan and generate_title in parallel",
    },
    STEP_COMPOSE_PLAN: {
        "description": (
            "用一次流式 LLM 把规划判断、资料边界、历史对话和最新反馈合成新的方案大纲。"
            "plan 标签内文本实时 SSE 给前端，完整输出解析为 suggestion、plan、chapters。"
            "调整方案时，这一步是唯一会重新调用的 Planner 生成模型。"
        ),
        "reads": ["material_context", "planning_note", "material_note", "message_history", "latest_plan", "feedback_message"],
        "writes": ["build_plan_draft", "plan_outline_markdown"],
        "input_keys": [
            "course_id",
            "material_context",
            "planning_note",
            "material_note",
            "user_prompt",
            "digest_mode",
            "model_override",
            "message_history",
            "latest_plan",
            "planner_session_id",
        ],
        "output_keys": ["build_plan_draft", "plan_outline_markdown", "compose_ms", "error"],
        "fanin": "joins generate_course_identity at save_planner_draft",
    },
    STEP_GENERATE_TITLE: {
        "description": (
            "仅在创建新 Planner 会话时运行，和方案大纲生成并行。"
            "根据规划判断、资料边界、资料文件名和 topic hints，通过一次结构化 LLM 生成 course_name 与 course_icon。"
            "调整方案时不重复生成课程身份。"
        ),
        "reads": ["material_context", "planning_note", "material_note", "user_prompt", "digest_mode"],
        "writes": ["generated_course_name", "generated_course_icon_key"],
        "input_keys": [
            "planner_operation",
            "material_context",
            "planning_note",
            "material_note",
            "user_prompt",
            "digest_mode",
            "model_override",
            "planner_session_id",
        ],
        "output_keys": ["generated_course_name", "generated_course_icon_key", "title_ms"],
        "fanin": "joins compose_planner_draft at save_planner_draft",
    },
    STEP_SAVE_PLAN: {
        "description": (
            "等待方案大纲和课程身份两个分支汇合，把 build_plan_draft 规范化成稳定 latest_plan。"
            "补齐章节索引、目标、required_elements、模式、course_name/course_icon，并写入 planner session 与 chat mirror。"
            "这里保存的是可继续调整的草案；用户确认后才会冻结为 DocGen 消费的 confirmed planner。"
        ),
        "reads": ["build_plan_draft", "generated_course_name", "material_context", "latest_plan"],
        "writes": ["plan", "planner_record", "planner_turns", "digest_mode"],
        "input_keys": [
            "course_id",
            "user_id",
            "planner_session_id",
            "build_plan_draft",
            "generated_course_name",
            "material_context",
            "latest_plan",
        ],
        "output_keys": [
            "plan",
            "planner_record",
            "planner_turns",
            "digest_mode",
            "finalize_ms",
            "error",
        ],
        "fanin": "compose_planner_draft + generate_course_identity",
    },
}


def _require_success_state(result: WorkflowResult[BuildPlannerState]) -> BuildPlannerState:
    state = result.require_value()
    error = str(state.get("error") or "").strip()
    if error:
        logger.warning(
            "planner_workflow_state_failed",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
            error=error,
        )
        raise WorkflowError(code="planner_failed", detail=error)
    return state


def _trace_planner_node(trace, step: str, handler, *, timing_field: str):
    details = NODE_TRACE_DETAILS[step]
    return traced_digest_node(
        trace,
        node_key=step,
        display_name=STEP_DISPLAY_NAMES[step],
        details=details,
        handler=handler,
        timing_field=timing_field,
    )


def _langgraph_node_metadata(step: str) -> dict[str, object]:
    return node_metadata(
        node_key=step,
        display_name=STEP_DISPLAY_NAMES[step],
        details=NODE_TRACE_DETAILS[step],
    )


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    """构建 Planner 的 LangGraph。

    Planner 只负责生成和修订可确认的方案：读取资料、生成规划判断/资料边界、
    并行生成课程身份与 suggestion/plan/chapters、保存方案。不要在这里做 DocGen 的资料读取、证据绑定或正文写作，
    也不要把 API 持久化细节塞进节点之外的地方。
    """

    trace = workflow_tracer(context=context, lane="planner")
    workflow = StateGraph(
        BuildPlannerState,
        input_schema=BuildPlannerGraphInput,
        output_schema=BuildPlannerGraphOutput,
    )

    workflow.add_node(
        STEP_LOAD_MATERIALS,
        _trace_planner_node(
            trace,
            STEP_LOAD_MATERIALS,
            build_collect_planner_context_node(context=context),
            timing_field="prepare_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_LOAD_MATERIALS),
    )
    workflow.add_node(
        STEP_UNDERSTAND_GOAL,
        _trace_planner_node(
            trace,
            STEP_UNDERSTAND_GOAL,
            build_understand_goal_and_materials_node(context=context),
            timing_field="bootstrap_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_UNDERSTAND_GOAL),
    )
    workflow.add_node(
        STEP_COMPOSE_PLAN,
        _trace_planner_node(
            trace,
            STEP_COMPOSE_PLAN,
            build_compose_planner_draft_node(context=context),
            timing_field="compose_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_COMPOSE_PLAN),
    )
    workflow.add_node(
        STEP_GENERATE_TITLE,
        _trace_planner_node(
            trace,
            STEP_GENERATE_TITLE,
            build_generate_course_identity_node(context=context),
            timing_field="title_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_GENERATE_TITLE),
    )
    workflow.add_node(
        STEP_SAVE_PLAN,
        _trace_planner_node(
            trace,
            STEP_SAVE_PLAN,
            build_save_planner_draft_node(context=context),
            timing_field="finalize_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_SAVE_PLAN),
    )

    workflow.set_entry_point(STEP_LOAD_MATERIALS)
    workflow.add_conditional_edges(
        STEP_LOAD_MATERIALS,
        route_after_step_for_trace,
        {"continue": STEP_UNDERSTAND_GOAL, "fail": END},
    )
    workflow.add_edge(STEP_UNDERSTAND_GOAL, STEP_COMPOSE_PLAN)
    workflow.add_edge(STEP_UNDERSTAND_GOAL, STEP_GENERATE_TITLE)
    workflow.add_edge([STEP_COMPOSE_PLAN, STEP_GENERATE_TITLE], STEP_SAVE_PLAN)
    workflow.add_edge(STEP_SAVE_PLAN, END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_step_for_trace(state: BuildPlannerState) -> str:
    return route_after_step(state)


route_after_step_for_trace = named_route(route_after_step_for_trace, "检查是否继续")


def create_planner_initial_state(
    *,
    course_id: str,
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_ids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    file_ids: list[str],
    user_prompt: str,
    digest_mode: str,
    planner_session_id: str,
    message_history: list[str],
    model: str | None = None,
    latest_plan: dict | None = None,
    diagnose_answers: list[dict] | None = None,
    diagnose_status: str = "",
    diagnose_note: str = "",
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerState:
    return {
        "course_id": course_id,
        "user_id": user_id,
        "planner_operation": planner_operation,
        "requested_file_ids": list(requested_file_ids or []),
        "session_title": session_title,
        "feedback_message": feedback_message,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "digest_mode": digest_mode,
        "model_override": model,
        "planner_session_id": planner_session_id,
        "message_history": message_history,
        "latest_plan": latest_plan,
        "diagnose_answers": list(diagnose_answers or []),
        "diagnose_status": diagnose_status,
        "diagnose_note": diagnose_note,
        "progress_callback": progress_callback,
        "token_callback": token_callback,
        "error": None,
    }


def get_langgraph_dev_planner_graph() -> StateGraph:
    return build_planner_graph(context=create_langgraph_dev_context("digest.planner.langgraph_dev"))


async def run_build_planner_workflow(
    *,
    course_id: str,
    file_ids: list[str],
    user_prompt: str,
    planner_session_id: str,
    digest_mode: str,
    message_history: list[str],
    model: str | None = None,
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_ids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    latest_plan: dict | None = None,
    diagnose_answers: list[dict] | None = None,
    diagnose_status: str = "",
    diagnose_note: str = "",
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> WorkflowResult[BuildPlannerState]:
    """Run the planner lane and return the final workflow state."""

    model_override = normalize_runtime_model_override(model)
    logger.info(
        "planner_workflow_starting",
        course_id=course_id,
        planner_session_id=planner_session_id,
        planner_operation=planner_operation,
        file_id_count=len(file_ids),
        requested_file_id_count=len(requested_file_ids or []),
        digest_mode=digest_mode,
        model_override=model_override,
        user_prompt_preview=user_prompt[:80],
    )
    normalized_operation = normalize_planner_operation(planner_operation)
    run_name = planner_trace_run_name(normalized_operation)
    context = WorkflowContext(
        workflow_name="digest.planner",
        course_id=course_id,
        metadata={
            "build_session_id": planner_session_id,
            "lane": "planner",
            "langsmith_run_name": run_name,
            "planner_operation": normalized_operation,
            "planner_session_id": planner_session_id,
            "digest_mode": digest_mode,
            "model_override": model_override,
        },
    )
    initial_state = create_planner_initial_state(
        course_id=course_id,
        user_id=user_id,
        planner_operation=planner_operation,
        requested_file_ids=requested_file_ids,
        session_title=session_title,
        feedback_message=feedback_message,
        file_ids=file_ids,
        user_prompt=user_prompt,
        digest_mode=digest_mode,
        planner_session_id=planner_session_id,
        message_history=message_history,
        model=model_override,
        latest_plan=latest_plan,
        diagnose_answers=diagnose_answers,
        diagnose_status=diagnose_status,
        diagnose_note=diagnose_note,
        progress_callback=progress_callback,
        token_callback=token_callback,
    )
    with use_runtime_model_override(model_override):
        result = await run_state_graph(
            workflow_name="digest.planner",
            graph_builder=lambda: build_planner_graph(context=context),
            initial_state=initial_state,
            context=context,
        )
    logger.info(
        "planner_workflow_finished",
        course_id=course_id,
        planner_session_id=planner_session_id,
        failed=result.failed,
        error=str(result.error) if result.error else "",
        has_value=result.value is not None,
        state_error=(result.value or {}).get("error") if isinstance(result.value, dict) else "",
    )
    return result


async def create_build_planner_session(
    *,
    course: Course,
    user_id: str,
    payload: BuildPlannerCreateRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    """创建一次新的 Planner 会话并流式生成首版方案。"""

    planner_defaults = get_teaching_runtime_config().planner
    session_id = uuid.uuid4().hex
    user_prompt = payload.user_prompt.strip()
    digest_mode = (payload.digest_mode or planner_defaults.default_digest_mode).strip() or planner_defaults.default_digest_mode
    logger.info(
        "planner_create_session_starting",
        course_id=course.id,
        user_id=user_id,
        planner_session_id=session_id,
        file_id_count=len(payload.file_ids or []),
        digest_mode=digest_mode,
        user_prompt_preview=user_prompt[:80],
    )
    try:
        result = await run_build_planner_workflow(
            course_id=course.id,
            user_id=user_id,
            planner_operation="create",
            requested_file_ids=list(payload.file_ids or []),
            session_title=payload.title or user_prompt,
            file_ids=[],
            user_prompt=user_prompt,
            planner_session_id=session_id,
            digest_mode=digest_mode,
            message_history=[user_prompt],
            model=payload.model,
            progress_callback=progress_callback,
            token_callback=token_callback,
        )
    except asyncio.CancelledError:
        _mark_planner_session_cancelled(course_id=course.id, user_id=user_id, session_id=session_id)
        raise
    if result.failed:
        _mark_planner_session_failed(course_id=course.id, user_id=user_id, session_id=session_id)
    try:
        final_state = _require_success_state(result)
    except Exception:
        _mark_planner_session_failed(course_id=course.id, user_id=user_id, session_id=session_id)
        raise
    logger.info(
        "planner_create_session_state_ready",
        course_id=course.id,
        planner_session_id=session_id,
        has_plan=bool(final_state.get("plan")),
        state_error=final_state.get("error"),
    )
    response = planner_session_response_from_state(final_state)
    _log_planner_runtime(course_id=course.id, session_id=response.session_id, final_state=final_state)
    return response


async def append_build_planner_message(
    *,
    course: Course,
    user_id: str,
    session_id: str,
    payload: BuildPlannerMessageRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    """在已有 Planner 会话中追加用户反馈并重新生成方案。"""

    logger.info(
        "planner_append_message_starting",
        course_id=course.id,
        user_id=user_id,
        planner_session_id=session_id,
        message_preview=payload.message[:80],
    )
    try:
        result = await run_build_planner_workflow(
            course_id=course.id,
            user_id=user_id,
            planner_operation="append",
            feedback_message=payload.message.strip(),
            file_ids=[],
            user_prompt="",
            planner_session_id=session_id,
            digest_mode="",
            message_history=[],
            model=payload.model,
            diagnose_answers=[
                item.model_dump(mode="json")
                for item in list(payload.diagnose_answers or [])
            ],
            diagnose_status=payload.diagnose_status or "",
            diagnose_note=payload.diagnose_note,
            progress_callback=progress_callback,
            token_callback=token_callback,
        )
    except asyncio.CancelledError:
        _mark_planner_session_cancelled(course_id=course.id, user_id=user_id, session_id=session_id)
        raise
    if result.failed:
        _mark_planner_session_failed(course_id=course.id, user_id=user_id, session_id=session_id)
    try:
        final_state = _require_success_state(result)
    except Exception:
        _mark_planner_session_failed(course_id=course.id, user_id=user_id, session_id=session_id)
        raise
    logger.info(
        "planner_append_message_state_ready",
        course_id=course.id,
        planner_session_id=session_id,
        has_plan=bool(final_state.get("plan")),
        state_error=final_state.get("error"),
    )
    response = planner_session_response_from_state(final_state)
    _log_planner_runtime(course_id=course.id, session_id=response.session_id, final_state=final_state)
    return response


def record_build_planner_adjust_click(
    session: Session,
    *,
    course: Course,
    user_id: str,
    session_id: str,
) -> dict[str, object]:
    """Record that the user opened the plan-adjust UI without mutating the plan."""

    context = get_planner_adjust_click_context(
        session,
        course=course,
        user_id=user_id,
        session_id=session_id,
    )
    logger.info(
        "planner_adjust_click_recorded",
        course_id=course.id,
        user_id=user_id,
        planner_session_id=session_id,
        has_latest_plan=context.get("has_latest_plan"),
    )
    return {
        "acknowledged": True,
        "planner_session_id": session_id,
        "course_id": course.id,
        "status": str(context.get("status") or ""),
        "has_latest_plan": bool(context.get("has_latest_plan")),
        "latest_plan_chapter_count": int(context.get("latest_plan_chapter_count") or 0),
    }


def _log_planner_runtime(*, course_id: str, session_id: str, final_state: Mapping[str, object]) -> None:
    elapsed_ms = int(final_state.get("workflow_elapsed_ms", 0) or 0)
    if elapsed_ms <= 0:
        return
    step_fields = {
        "collect_planner_context": "prepare_ms",
        "understand_goal_and_materials": "bootstrap_ms",
        "compose_planner_draft": "compose_ms",
        "generate_course_identity": "title_ms",
        "save_planner_draft": "finalize_ms",
    }
    logger.info(
        "planner_runtime_summary",
        course_id=course_id,
        planner_session_id=session_id,
        elapsed_ms=elapsed_ms,
        steps=[
            {"name": name, "elapsed_ms": int(final_state.get(field, 0) or 0)}
            for name, field in step_fields.items()
            if int(final_state.get(field, 0) or 0) > 0
        ],
    )


def _mark_planner_session_failed(*, course_id: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_failed(course_id=course_id, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_failed_status_update_failed", course_id=course_id, session_id=session_id)


def _mark_planner_session_cancelled(*, course_id: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_cancelled(course_id=course_id, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_cancelled_status_update_failed", course_id=course_id, session_id=session_id)


def _mark_planner_session_draft(*, course_id: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_draft(course_id=course_id, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_draft_status_update_failed", course_id=course_id, session_id=session_id)


__all__ = [
    "append_build_planner_message",
    "build_planner_graph",
    "create_build_planner_session",
    "create_planner_initial_state",
    "get_langgraph_dev_planner_graph",
    "record_build_planner_adjust_click",
    "route_after_step",
    "run_build_planner_workflow",
]
