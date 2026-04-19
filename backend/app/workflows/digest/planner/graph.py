"""Planner graph definition and public workflow entrypoints.

真实链路只有四步：读取资料 -> 理解目标 -> 合成大纲 -> 保存方案。
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from langgraph.graph import END, StateGraph

from app.models.subject import Subject
from app.schemas.knowledge import BuildPlannerCreateRequest, BuildPlannerMessageRequest, BuildPlannerSessionResponse
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowError, WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.store import (
    mark_planner_session_draft,
    mark_planner_session_failed,
    planner_session_response_from_state,
)
from app.workflows.digest.planner.lib.steps import (
    STEP_COMPOSE_PLAN,
    STEP_DISPLAY_NAMES,
    STEP_LOAD_MATERIALS,
    STEP_SAVE_PLAN,
    STEP_UNDERSTAND_GOAL,
)
from app.workflows.digest.planner.nodes import (
    build_load_planner_materials_node,
    build_normalize_and_persist_plan_node,
    build_stream_and_parse_plan_draft_node,
    build_stream_brief_and_extract_intent_node,
)
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)

logger = structlog.get_logger(__name__)

RUN_NAME_PLANNER = "规划引擎：生成构建方案"


def _require_success_state(result: WorkflowResult[BuildPlannerState]) -> BuildPlannerState:
    state = result.require_value()
    error = str(state.get("error") or "").strip()
    if error:
        logger.warning(
            "planner_workflow_state_failed",
            planner_session_id=state.get("planner_session_id", ""),
            subject=state.get("subject", ""),
            error=error,
        )
        raise WorkflowError(code="planner_failed", detail=error)
    return state


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    trace = workflow_tracer(context=context, lane="planner")
    workflow = StateGraph(
        BuildPlannerState,
        input_schema=BuildPlannerGraphInput,
        output_schema=BuildPlannerGraphOutput,
    )

    workflow.add_node(
        STEP_LOAD_MATERIALS,
        trace.node(
            build_load_planner_materials_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_LOAD_MATERIALS],
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        STEP_UNDERSTAND_GOAL,
        trace.node(
            build_stream_brief_and_extract_intent_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_UNDERSTAND_GOAL],
            timing_field="bootstrap_ms",
        ),
    )
    workflow.add_node(
        STEP_COMPOSE_PLAN,
        trace.node(
            build_stream_and_parse_plan_draft_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_COMPOSE_PLAN],
            timing_field="compose_ms",
        ),
    )
    workflow.add_node(
        STEP_SAVE_PLAN,
        trace.node(
            build_normalize_and_persist_plan_node(context=context),
            name=STEP_DISPLAY_NAMES[STEP_SAVE_PLAN],
            timing_field="finalize_ms",
        ),
    )
    workflow.set_entry_point(STEP_LOAD_MATERIALS)
    workflow.add_conditional_edges(
        STEP_LOAD_MATERIALS,
        route_after_step_for_trace,
        {"continue": STEP_UNDERSTAND_GOAL, "fail": END},
    )
    workflow.add_conditional_edges(
        STEP_UNDERSTAND_GOAL,
        route_after_step_for_trace,
        {"continue": STEP_COMPOSE_PLAN, "fail": END},
    )
    workflow.add_conditional_edges(
        STEP_COMPOSE_PLAN,
        route_after_step_for_trace,
        {"continue": STEP_SAVE_PLAN, "fail": END},
    )
    workflow.add_edge(STEP_SAVE_PLAN, END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_step_for_trace(state: BuildPlannerState) -> str:
    return route_after_step(state)


route_after_step_for_trace.__name__ = "检查是否继续"
route_after_step_for_trace.__qualname__ = "检查是否继续"


def create_planner_initial_state(
    *,
    subject: str,
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_uids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    file_ids: list[int],
    user_goal: str,
    digest_mode: str,
    planner_session_id: str,
    message_history: list[str],
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerState:
    # planner_operation 只区分“直接调图调试”和“API create/append”；
    # 不管哪种入口，下面跑的都是同一条 graph。
    return {
        "subject": subject,
        "user_id": user_id,
        "planner_operation": planner_operation,
        "requested_file_uids": list(requested_file_uids or []),
        "session_title": session_title,
        "feedback_message": feedback_message,
        "file_ids": file_ids,
        "user_goal": user_goal,
        "digest_mode": digest_mode,
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
    subject: str,
    file_ids: list[int],
    user_goal: str,
    planner_session_id: str,
    digest_mode: str,
    message_history: list[str],
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_uids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> WorkflowResult[BuildPlannerState]:
    """Run the planner lane and return the final workflow state."""

    logger.info(
        "planner_workflow_starting",
        subject=subject,
        planner_session_id=planner_session_id,
        planner_operation=planner_operation,
        file_id_count=len(file_ids),
        requested_file_uid_count=len(requested_file_uids or []),
        digest_mode=digest_mode,
        user_goal_preview=user_goal[:80],
    )
    context = WorkflowContext(
        workflow_name="digest.planner",
        subject=subject,
        metadata={
            "build_session_id": planner_session_id,
            "lane": "planner",
            "langsmith_run_name": RUN_NAME_PLANNER,
            "planner_session_id": planner_session_id,
            "digest_mode": digest_mode,
        },
    )
    result = await run_state_graph(
        workflow_name="digest.planner",
        graph_builder=lambda: build_planner_graph(context=context),
        initial_state=create_planner_initial_state(
            subject=subject,
            user_id=user_id,
            planner_operation=planner_operation,
            requested_file_uids=requested_file_uids,
            session_title=session_title,
            feedback_message=feedback_message,
            file_ids=file_ids,
            user_goal=user_goal,
            digest_mode=digest_mode,
            planner_session_id=planner_session_id,
            message_history=message_history,
            latest_plan=latest_plan,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
        context=context,
    )
    logger.info(
        "planner_workflow_finished",
        subject=subject,
        planner_session_id=planner_session_id,
        failed=result.failed,
        error=str(result.error) if result.error else "",
        has_value=result.value is not None,
        state_error=(result.value or {}).get("error") if isinstance(result.value, dict) else "",
    )
    return result


async def create_build_planner_session(
    *,
    subject: Subject,
    user_id: str,
    payload: BuildPlannerCreateRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    # API 友好入口：只装配 state、启动 graph、把最终 state 转成既有响应结构。
    # 真正业务逻辑仍在 graph nodes 里。
    planner_defaults = get_teaching_runtime_config().planner
    session_id = uuid.uuid4().hex
    user_goal = payload.user_goal.strip()
    digest_mode = (payload.digest_mode or planner_defaults.default_digest_mode).strip() or planner_defaults.default_digest_mode
    logger.info(
        "planner_create_session_starting",
        subject=subject.slug,
        user_id=user_id,
        planner_session_id=session_id,
        file_uid_count=len(payload.file_uids or []),
        digest_mode=digest_mode,
        user_goal_preview=user_goal[:80],
    )
    try:
        result = await run_build_planner_workflow(
            subject=subject.slug,
            user_id=user_id,
            planner_operation="create",
            requested_file_uids=list(payload.file_uids or []),
            session_title=payload.title or user_goal or subject.name,
            file_ids=[],
            user_goal=user_goal,
            planner_session_id=session_id,
            digest_mode=digest_mode,
            message_history=[user_goal],
            progress_callback=progress_callback,
            token_callback=token_callback,
        )
    except asyncio.CancelledError:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
        raise
    if result.failed:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
    try:
        final_state = _require_success_state(result)
    except Exception:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
        raise
    logger.info(
        "planner_create_session_state_ready",
        subject=subject.slug,
        planner_session_id=session_id,
        has_plan=bool(final_state.get("plan")),
        state_error=final_state.get("error"),
    )
    response = planner_session_response_from_state(final_state)
    _log_planner_runtime(subject=subject.slug, response=response)
    return response


async def append_build_planner_message(
    *,
    subject: Subject,
    user_id: str,
    session_id: str,
    payload: BuildPlannerMessageRequest,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerSessionResponse:
    # 追加反馈也只是同一条 graph run。
    # load_planner_materials 会读取上一版 session/plan 并追加用户 turn。
    logger.info(
        "planner_append_message_starting",
        subject=subject.slug,
        user_id=user_id,
        planner_session_id=session_id,
        message_preview=payload.message[:80],
    )
    try:
        result = await run_build_planner_workflow(
            subject=subject.slug,
            user_id=user_id,
            planner_operation="append",
            feedback_message=payload.message.strip(),
            file_ids=[],
            user_goal="",
            planner_session_id=session_id,
            digest_mode="",
            message_history=[],
            progress_callback=progress_callback,
            token_callback=token_callback,
        )
    except asyncio.CancelledError:
        _mark_planner_session_draft(subject=subject.slug, user_id=user_id, session_id=session_id)
        raise
    if result.failed:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
    try:
        final_state = _require_success_state(result)
    except Exception:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
        raise
    logger.info(
        "planner_append_message_state_ready",
        subject=subject.slug,
        planner_session_id=session_id,
        has_plan=bool(final_state.get("plan")),
        state_error=final_state.get("error"),
    )
    response = planner_session_response_from_state(final_state)
    _log_planner_runtime(subject=subject.slug, response=response)
    return response


def _log_planner_runtime(*, subject: str, response: BuildPlannerSessionResponse) -> None:
    runtime_stats = response.runtime_stats
    if runtime_stats is None:
        return
    logger.info(
        "planner_runtime_summary",
        subject=subject,
        planner_session_id=response.session_id,
        elapsed_ms=runtime_stats.elapsed_ms,
        steps=[step.model_dump(mode="json") for step in runtime_stats.steps],
    )


def _mark_planner_session_failed(*, subject: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_failed(subject=subject, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_failed_status_update_failed", subject=subject, session_id=session_id)


def _mark_planner_session_draft(*, subject: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_draft(subject=subject, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_draft_status_update_failed", subject=subject, session_id=session_id)


__all__ = [
    "append_build_planner_message",
    "build_planner_graph",
    "create_build_planner_session",
    "create_planner_initial_state",
    "get_langgraph_dev_planner_graph",
    "route_after_step",
    "run_build_planner_workflow",
]
