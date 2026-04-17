"""Planner graph definition and public workflow entrypoints.

Planner 只有一条真实业务链路：
prepare material -> summarize -> brief/intent -> evidence -> compose -> finalize。
create/append API 只负责装配初始 state 并启动这条图；session DB 读写发生在
prepare/finalize 这两个真实节点里，通过极简 store API 完成。
"""

from __future__ import annotations

import uuid

import structlog
from langgraph.graph import END, StateGraph

from app.models.subject import Subject
from app.schemas.knowledge import BuildPlannerCreateRequest, BuildPlannerMessageRequest, BuildPlannerSessionResponse
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.contracts import resolve_planner_retrieval_profile
from app.workflows.digest.common.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.store import (
    mark_planner_session_failed,
    planner_session_response_from_state,
)
from app.workflows.digest.planner.nodes import (
    build_bootstrap_plan_brief_node,
    build_compose_build_plan_node,
    build_finalize_plan_contract_node,
    build_prepare_material_context_node,
    build_probe_evidence_node,
    build_summarize_material_digest_node,
)
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)

logger = structlog.get_logger(__name__)


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    trace = workflow_tracer(context=context, lane="planner")
    workflow = StateGraph(
        BuildPlannerState,
        input_schema=BuildPlannerGraphInput,
        output_schema=BuildPlannerGraphOutput,
    )

    # API create/append 场景下，资料准备节点也是第一处持久化点：
    # 先创建或读取 planner session，再准备 material_context。
    workflow.add_node(
        "prepare_material_context",
        trace.node(
            build_prepare_material_context_node(context=context),
            name="prepare_material_context",
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        "summarize_material_digest",
        trace.node(
            build_summarize_material_digest_node(context=context),
            name="summarize_material_digest",
            timing_field="digest_ms",
        ),
    )

    # 规划展示层：一边流式输出用户可见 planning brief，
    # 一边并行抽取极简 learning intent。
    workflow.add_node(
        "bootstrap_plan_brief",
        trace.node(
            build_bootstrap_plan_brief_node(context=context),
            name="bootstrap_plan_brief",
            timing_field="bootstrap_ms",
        ),
    )

    # 证据探测层：把检索细节压缩成 EvidenceBrief，
    # 避免 composer 直接吃一堆 raw hits。
    workflow.add_node(
        "probe_evidence",
        trace.node(
            build_probe_evidence_node(context=context),
            name="probe_evidence",
            timing_field="evidence_ms",
        ),
    )
    workflow.add_node(
        "compose_build_plan",
        trace.node(
            build_compose_build_plan_node(context=context),
            name="compose_build_plan",
            timing_field="compose_ms",
        ),
    )

    # 合同收口层：normalize BuildPlannerDraft，并在 API create/append 场景下
    # 保存 latest_plan。不要再额外拆 service/session 节点。
    workflow.add_node(
        "finalize_plan_contract",
        trace.node(
            build_finalize_plan_contract_node(context=context),
            name="finalize_plan_contract",
            timing_field="finalize_ms",
        ),
    )
    workflow.set_entry_point("prepare_material_context")
    workflow.add_conditional_edges(
        "prepare_material_context",
        route_after_step,
        {"continue": "summarize_material_digest", "fail": END},
    )
    workflow.add_conditional_edges(
        "summarize_material_digest",
        route_after_step,
        {"continue": "bootstrap_plan_brief", "fail": END},
    )
    workflow.add_conditional_edges(
        "bootstrap_plan_brief",
        route_after_step,
        {"continue": "probe_evidence", "fail": END},
    )
    workflow.add_conditional_edges(
        "probe_evidence",
        route_after_step,
        {"continue": "compose_build_plan", "fail": END},
    )
    workflow.add_conditional_edges(
        "compose_build_plan",
        route_after_step,
        {"continue": "finalize_plan_contract", "fail": END},
    )
    workflow.add_edge("finalize_plan_contract", END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def create_planner_initial_state(
    *,
    subject: str,
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_uids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    selected_skillpacks_override: bool = True,
    file_ids: list[int],
    user_goal: str,
    digest_mode: str,
    tone: str,
    selected_skillpacks: list[str],
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
        "selected_skillpacks_override": selected_skillpacks_override,
        "file_ids": file_ids,
        "user_goal": user_goal,
        "digest_mode": digest_mode,
        "retrieval_profile": resolve_planner_retrieval_profile(),
        "tone": tone,
        "selected_skillpacks": list(selected_skillpacks),
        "planner_session_id": planner_session_id,
        "message_history": message_history,
        "latest_plan": latest_plan,
        "progress_callback": progress_callback,
        "token_callback": token_callback,
        "generation_mode": "research_surface_v4",
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
    tone: str,
    selected_skillpacks: list[str],
    message_history: list[str],
    user_id: str = "",
    planner_operation: str = "generate_only",
    requested_file_uids: list[str] | None = None,
    session_title: str = "",
    feedback_message: str = "",
    selected_skillpacks_override: bool = True,
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> WorkflowResult[BuildPlannerState]:
    """Run the planner lane and return the final workflow state."""

    context = WorkflowContext(
        workflow_name="digest.planner",
        subject=subject,
        metadata={
            "build_session_id": planner_session_id,
            "lane": "planner",
            "planner_session_id": planner_session_id,
            "digest_mode": digest_mode,
        },
    )
    return await run_state_graph(
        workflow_name="digest.planner",
        graph_builder=lambda: build_planner_graph(context=context),
        initial_state=create_planner_initial_state(
            subject=subject,
            user_id=user_id,
            planner_operation=planner_operation,
            requested_file_uids=requested_file_uids,
            session_title=session_title,
            feedback_message=feedback_message,
            selected_skillpacks_override=selected_skillpacks_override,
            file_ids=file_ids,
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            selected_skillpacks=selected_skillpacks,
            planner_session_id=planner_session_id,
            message_history=message_history,
            latest_plan=latest_plan,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
        context=context,
    )


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
    tone = (payload.tone or planner_defaults.default_tone).strip() or planner_defaults.default_tone
    result = await run_build_planner_workflow(
        subject=subject.slug,
        user_id=user_id,
        planner_operation="create",
        requested_file_uids=list(payload.file_uids or []),
        session_title=(payload.title or user_goal or subject.name)[:120],
        file_ids=[],
        user_goal=user_goal,
        planner_session_id=session_id,
        digest_mode=digest_mode,
        tone=tone,
        selected_skillpacks=list(payload.selected_skillpacks or []),
        message_history=[user_goal],
        progress_callback=progress_callback,
        token_callback=token_callback,
    )
    if result.failed:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
    response = planner_session_response_from_state(result.require_value())
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
    # prepare_material_context 会读取上一版 session/plan 并追加用户 turn。
    result = await run_build_planner_workflow(
        subject=subject.slug,
        user_id=user_id,
        planner_operation="append",
        feedback_message=payload.message.strip(),
        selected_skillpacks_override=payload.selected_skillpacks is not None,
        file_ids=[],
        user_goal="",
        planner_session_id=session_id,
        digest_mode="",
        tone="",
        selected_skillpacks=list(payload.selected_skillpacks or []),
        message_history=[],
        progress_callback=progress_callback,
        token_callback=token_callback,
    )
    if result.failed:
        _mark_planner_session_failed(subject=subject.slug, user_id=user_id, session_id=session_id)
    response = planner_session_response_from_state(result.require_value())
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
        generation_mode=runtime_stats.generation_mode,
    )


def _mark_planner_session_failed(*, subject: str, user_id: str, session_id: str) -> None:
    try:
        mark_planner_session_failed(subject=subject, user_id=user_id, session_id=session_id)
    except Exception:
        logger.exception("planner_session_failed_status_update_failed", subject=subject, session_id=session_id)


__all__ = [
    "append_build_planner_message",
    "build_planner_graph",
    "create_build_planner_session",
    "create_planner_initial_state",
    "get_langgraph_dev_planner_graph",
    "route_after_step",
    "run_build_planner_workflow",
]
