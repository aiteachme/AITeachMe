"""Digest DocGen workflow package."""

from __future__ import annotations

from datetime import datetime

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.shared.infra.settings import get_settings
from app.workflows.digest.common.metrics import build_token_summary
from app.workflows.digest.docgen.lib.build_lifecycle import (
    get_docgen_result,
    run_docgen_background,
    trigger_docgen_build,
)
from app.workflows.digest.common.cleanup import clear_subject_knowledge
from app.workflows.digest.docgen.graph import (
    RUN_NAME_DOCGEN,
    build_docgen_graph,
    create_docgen_initial_state,
    get_langgraph_dev_docgen_graph,
)
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.common.events import (
    DocGenCompletedEvent,
    DocGenFailedEvent,
    DocGenRequestedEvent,
)


async def run_docgen_workflow(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime,
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
    shared_inputs: object | None = None,
    confirmed_plan: dict | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
) -> WorkflowResult[DocGenState]:
    """运行一次 DocGen LangGraph。

    这里只负责创建 workflow context、装配初始 state、执行图、汇总 token /
    timing 并发布完成或失败事件。构建锁、文件选择和后台任务生命周期不在
    这里处理，而是在 `lib.build_lifecycle`。
    """

    bus = event_bus or InProcessEventBus()
    settings = get_settings()
    await bus.publish(DocGenRequestedEvent(subject=subject, requested_at=requested_at, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject=subject,
        event_bus=bus,
        metadata={
            "requested_at": requested_at.isoformat(),
            "lane": "docgen",
            "langsmith_run_name": RUN_NAME_DOCGEN,
            "build_session_id": build_session_id or "",
            "planner_session_id": planner_session_id or "",
            "confirmed_plan_id": confirmed_plan_id or "",
            "digest_mode": digest_mode or "",
            "max_concurrency": max(1, int(settings.docgen.max_parallel_chapters)),
        },
    )
    result = await run_state_graph(
        workflow_name="digest.docgen",
        graph_builder=lambda: build_docgen_graph(context=context),
        initial_state=create_docgen_initial_state(
            subject=subject,
            file_ids=file_ids,
            user_prompt=user_prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
            shared_inputs=shared_inputs,
            confirmed_plan=confirmed_plan,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=digest_mode,
        ),
        context=context,
    )
    if result.failed:
        token_summary = build_token_summary(build_session_id=build_session_id or None, lane="docgen")
        context.get_logger().bind(node="runtime").info(
            "docgen_timing_summary",
            **build_docgen_lane_summary(
                {},
                token_summary=token_summary,
                status="failed",
                error_message=result.error.detail,
            ),
        )
        await bus.publish(
            DocGenFailedEvent(
                subject=subject,
                requested_at=requested_at,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    docgen_token_summary = build_token_summary(
        build_session_id=final_state.get("build_session_id") or build_session_id or None,
        lane="docgen",
    )
    final_state["token_summary"] = docgen_token_summary.model_dump()
    final_state["timing_summary"] = build_docgen_lane_summary(
        final_state,
        token_summary=docgen_token_summary,
    )
    context.get_logger().bind(node="runtime").info(
        "docgen_timing_summary",
        **final_state["timing_summary"],
    )
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            DocGenFailedEvent(
                subject=subject,
                requested_at=requested_at,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_docgen_failed",
            error_message,
            metadata={"requested_at": requested_at.isoformat(), "subject": subject},
        )

    await bus.publish(
        DocGenCompletedEvent(
            subject=subject,
            requested_at=requested_at,
            staged_chapter_count=len(final_state.get("chapter_metadatas", [])),
            draft_available=bool(str(final_state.get("merged_markdown", "")).strip()),
            published_doc_count=len(final_state.get("doc_ids", [])),
        )
    )
    return result


__all__ = [
    "DocGenState",
    "build_docgen_graph",
    "clear_subject_knowledge",
    "create_docgen_initial_state",
    "get_docgen_result",
    "get_langgraph_dev_docgen_graph",
    "run_docgen_background",
    "run_docgen_workflow",
    "trigger_docgen_build",
]
