"""Planner graph definition and public workflow entrypoints.

真实链路主线：读取资料 -> 理解目标 ->（并行：生成标题 / 合成大纲）-> 保存方案。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

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
from app.workflows.digest.planner.nodes.generate_course_name import build_generate_course_name_node
from app.workflows.digest.planner.nodes.load_planner_materials import build_load_planner_materials_node
from app.workflows.digest.planner.nodes.normalize_and_persist_plan import (
    build_normalize_and_persist_plan_node,
)
from app.workflows.digest.planner.nodes.stream_and_parse_plan_draft import (
    build_stream_and_parse_plan_draft_node,
)
from app.workflows.digest.planner.nodes.stream_brief_and_extract_intent import (
    build_stream_brief_and_extract_intent_node,
)
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)

logger = structlog.get_logger(__name__)

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    STEP_LOAD_MATERIALS: {
        "description": (
            "读取或创建 Planner 会话，解析 create/append 请求中的资料选择、历史消息和最新方案，"
            "并加载本轮可用的 DigestMaterialContext。若资料正文尚未解析完成，会基于文件名、用户提示和课程元信息生成 seed context，"
            "保证 Planner 能先产出可继续修改的临时方案。"
        ),
        "reads": ["planner_session", "raw_file", "parsed_markdown", "material_digest_cache", "latest_plan"],
        "writes": ["selected_file_ids", "material_context", "digest_mode"],
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
            "material_context",
            "digest_mode",
            "prepare_ms",
            "error",
        ],
    },
    STEP_UNDERSTAND_GOAL: {
        "description": (
            "并行执行两个轻规划动作：一边流式生成用户可见的资料边界/学习目标判断，一边抽取内部 PlanIntent。"
            "输出 planner_brief 和 plan_intent，供后续大纲合成与标题生成共用；这个节点不写最终章节合同。"
        ),
        "reads": ["material_context", "user_prompt", "digest_mode", "message_history"],
        "writes": ["planner_brief", "plan_intent"],
        "input_keys": ["course_id", "material_context", "user_prompt", "digest_mode", "message_history", "planner_session_id", "model_override"],
        "output_keys": ["planner_brief", "plan_intent", "bootstrap_ms", "error"],
        "fanout": "internal_async_brief_and_intent",
        "routing": "after this node, LangGraph runs compose_plan and generate_title in parallel",
    },
    STEP_COMPOSE_PLAN: {
        "description": (
            "基于 material_context、planner_brief、plan_intent、历史消息和 latest_plan 流式生成可见计划说明，"
            "同时解析隐藏 JSON 机器合同，得到 build_plan_draft。若模型 JSON 不完整，会再走结构化模型修复；修复失败则让 Planner 明确失败。"
        ),
        "reads": ["material_context", "planner_brief", "plan_intent", "message_history", "latest_plan"],
        "writes": ["build_plan_draft", "plan_outline_markdown"],
        "input_keys": [
            "course_id",
            "material_context",
            "planner_brief",
            "plan_intent",
            "user_prompt",
            "digest_mode",
            "model_override",
            "message_history",
            "latest_plan",
            "planner_session_id",
        ],
        "output_keys": ["build_plan_draft", "plan_outline_markdown", "compose_ms", "error"],
        "fanin": "joins STEP_GENERATE_TITLE at STEP_SAVE_PLAN",
    },
    STEP_GENERATE_TITLE: {
        "description": (
            "仅在创建新 Planner 会话时运行，和大纲合成并行。它根据资料文件名、topic hints、planner_brief 和 plan_intent "
            "生成短课程标题，并选择课程图标；不会依赖最终大纲，也不会改章节计划。"
        ),
        "reads": ["material_context", "planner_brief", "plan_intent", "user_prompt", "digest_mode"],
        "writes": ["generated_course_name", "generated_course_icon_key"],
        "input_keys": [
            "planner_operation",
            "material_context",
            "planner_brief",
            "plan_intent",
            "user_prompt",
            "digest_mode",
            "model_override",
            "planner_session_id",
        ],
        "output_keys": ["generated_course_name", "generated_course_icon_key", "title_ms"],
        "fanin": "joins STEP_COMPOSE_PLAN at STEP_SAVE_PLAN",
    },
    STEP_SAVE_PLAN: {
        "description": (
            "等待大纲草稿和标题分支 fan-in 后，把 build_plan_draft 规范化成稳定 BuildPlan 合同，"
            "补齐章节索引、目标、required_elements、模式和摘要，再写入 planner session / chat mirror。"
            "这是 Planner 的发布边界，DocGen 只消费这里保存后的 confirmed plan。"
        ),
        "reads": ["build_plan_draft", "generated_course_name", "material_context", "latest_plan"],
        "writes": ["plan", "plan_summary", "planner_record", "planner_turns", "digest_mode"],
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
            "plan_summary",
            "planner_record",
            "planner_turns",
            "digest_mode",
            "finalize_ms",
            "error",
        ],
        "fanin": "STEP_COMPOSE_PLAN + STEP_GENERATE_TITLE",
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

    Planner 只负责生成和修订可确认的构建方案：读取资料、理解目标、
    并行生成标题与大纲、保存方案。不要在这里做 DocGen 的检索写作，
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
            build_load_planner_materials_node(context=context),
            timing_field="prepare_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_LOAD_MATERIALS),
    )
    workflow.add_node(
        STEP_UNDERSTAND_GOAL,
        _trace_planner_node(
            trace,
            STEP_UNDERSTAND_GOAL,
            build_stream_brief_and_extract_intent_node(context=context),
            timing_field="bootstrap_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_UNDERSTAND_GOAL),
    )
    workflow.add_node(
        STEP_COMPOSE_PLAN,
        _trace_planner_node(
            trace,
            STEP_COMPOSE_PLAN,
            build_stream_and_parse_plan_draft_node(context=context),
            timing_field="compose_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_COMPOSE_PLAN),
    )
    workflow.add_node(
        STEP_GENERATE_TITLE,
        _trace_planner_node(
            trace,
            STEP_GENERATE_TITLE,
            build_generate_course_name_node(context=context),
            timing_field="title_ms",
        ),
        metadata=_langgraph_node_metadata(STEP_GENERATE_TITLE),
    )
    workflow.add_node(
        STEP_SAVE_PLAN,
        _trace_planner_node(
            trace,
            STEP_SAVE_PLAN,
            build_normalize_and_persist_plan_node(context=context),
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
    _log_planner_runtime(course_id=course.id, response=response)
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
    _log_planner_runtime(course_id=course.id, response=response)
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


def _log_planner_runtime(*, course_id: str, response: BuildPlannerSessionResponse) -> None:
    runtime_stats = response.runtime_stats
    if runtime_stats is None:
        return
    logger.info(
        "planner_runtime_summary",
        course_id=course_id,
        planner_session_id=response.session_id,
        elapsed_ms=runtime_stats.elapsed_ms,
        steps=[step.model_dump(mode="json") for step in runtime_stats.steps],
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
