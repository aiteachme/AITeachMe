"""Planner workflow runtime."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.digest.planner.graph import build_planner_graph, create_planner_initial_state
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.contracts import (
    resolve_digest_course_type,
    resolve_planner_retrieval_profile,
)


async def run_build_planner_workflow(
    *,
    subject: str,
    file_ids: list[int],
    user_goal: str,
    planner_session_id: str,
    digest_mode: str,
    tone: str,
    message_history: list[str],
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> WorkflowResult[BuildPlannerState]:
    course_type = resolve_digest_course_type(digest_mode)
    context = WorkflowContext(
        workflow_name="digest.planner",
        subject=subject,
        metadata={
            "planner_session_id": planner_session_id,
            "build_session_id": planner_session_id,
            "lane": "planner",
            "digest_mode": digest_mode,
            "course_type": course_type,
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "teaching_action": "plan_course",
        },
    )
    result = await run_state_graph(
        workflow_name="digest.planner",
        graph_builder=lambda: build_planner_graph(context=context),
        initial_state=create_planner_initial_state(
            subject=subject,
            file_ids=file_ids,
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            planner_session_id=planner_session_id,
            message_history=message_history,
            latest_plan=latest_plan,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
        context=context,
    )
    if result.failed:
        return result
    final_state = result.require_value()
    if final_state.get("error"):
        return err_result("planner_failed", str(final_state.get("error")))
    return result


__all__ = ["run_build_planner_workflow"]
