"""Unified digest runtime entrypoint."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter

import structlog

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.observability import build_token_summary, build_unified_timing_report
from app.workflows.digest.unified.events import (
    UnifiedBuildCompletedEvent,
    UnifiedBuildFailedEvent,
    UnifiedBuildStartedEvent,
)
from app.workflows.digest.unified.graph import build_unified_digest_graph, create_unified_initial_state
from app.workflows.digest.unified.state import UnifiedBuildResult

logger = structlog.get_logger()


async def run_unified_digest_build(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime | None = None,
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
    confirmed_plan: dict | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
    tone: str | None = None,
) -> UnifiedBuildResult:
    """Run the top-level unified digest build."""

    bus = event_bus or InProcessEventBus()
    requested_at = requested_at or datetime.now()
    started_at = perf_counter()

    await bus.publish(UnifiedBuildStartedEvent(subject=subject, file_count=len(file_ids)))
    initial_state = create_unified_initial_state(
        subject=subject,
        file_ids=file_ids,
        user_prompt=user_prompt,
        requested_at=requested_at,
        build_session_id=build_session_id,
        confirmed_plan=confirmed_plan,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        digest_mode=digest_mode,
        tone=tone,
    )
    build_session_id = initial_state["build_session_id"]
    context = WorkflowContext(
        workflow_name="digest.unified",
        subject=subject,
        event_bus=bus,
        metadata={
            "requested_at": requested_at.isoformat(),
            "build_session_id": build_session_id,
            "planner_session_id": planner_session_id or "",
            "confirmed_plan_id": confirmed_plan_id or "",
            "digest_mode": digest_mode or "",
        },
    )
    result = await run_state_graph(
        workflow_name="digest.unified",
        graph_builder=lambda: build_unified_digest_graph(context=context),
        initial_state=initial_state,
        context=context,
    )

    if result.failed:
        error_message = result.error.detail
        token_summary = build_token_summary(build_session_id=build_session_id or None)
        timing_report = build_unified_timing_report(
            final_state={
                "build_session_id": build_session_id,
                "planner_session_id": planner_session_id or "",
                "confirmed_plan_id": confirmed_plan_id or "",
            },
            status="failed",
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            llm_summary=token_summary,
        )
        logger.info("unified_digest_timing_summary", **timing_report.model_dump(mode="json"))
        await bus.publish(
            UnifiedBuildFailedEvent(
                subject=subject,
                build_session_id=build_session_id,
                error_message=error_message,
            )
        )
        return UnifiedBuildResult(
            subject=subject,
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            success=False,
            error=error_message,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            timing_report=timing_report.model_dump(mode="json"),
            token_summary=token_summary.model_dump(mode="json"),
        )

    final_state = result.require_value()
    build_session_id = final_state.get("build_session_id", "")
    planner_session_id = final_state.get("planner_session_id") or planner_session_id
    confirmed_plan_id = final_state.get("confirmed_plan_id") or confirmed_plan_id
    unified_token_summary = build_token_summary(build_session_id=build_session_id or None)
    error_message = final_state.get("error")
    if error_message:
        timing_report = build_unified_timing_report(
            final_state=final_state,
            status="failed",
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            llm_summary=unified_token_summary,
        )
        logger.info("unified_digest_timing_summary", **timing_report.model_dump(mode="json"))
        await bus.publish(
            UnifiedBuildFailedEvent(
                subject=subject,
                build_session_id=build_session_id,
                error_message=error_message,
            )
        )
        return UnifiedBuildResult(
            subject=subject,
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            success=False,
            error=error_message,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            shared_prepare_ms=int(final_state.get("shared_prepare_ms", 0)),
            doc_lane_ms=int(final_state.get("doc_lane_ms", 0)),
            kg_lane_ms=int(final_state.get("kg_lane_ms", 0)),
            timing_report=timing_report.model_dump(mode="json"),
            token_summary=unified_token_summary.model_dump(mode="json"),
        )

    doc_state = final_state.get("doc_state", {})
    kg_state = final_state.get("kg_state", {})

    elapsed_ms = int((perf_counter() - started_at) * 1000)
    timing_report = build_unified_timing_report(
        final_state=final_state,
        status="completed",
        elapsed_ms=elapsed_ms,
        llm_summary=unified_token_summary,
    )
    final_state["token_summary"] = unified_token_summary.model_dump(mode="json")
    final_state["timing_report"] = timing_report.model_dump(mode="json")
    unified_result = UnifiedBuildResult(
        subject=subject,
        build_session_id=build_session_id,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        success=True,
        doc_count=len(doc_state.get("doc_ids", [])),
        doc_ids=list(doc_state.get("doc_ids", [])),
        chunk_count=len(kg_state.get("chunk_ids", [])),
        new_node_count=len(kg_state.get("new_node_ids", [])),
        new_edge_count=len(kg_state.get("new_edge_ids", [])),
        elapsed_ms=elapsed_ms,
        shared_prepare_ms=int(final_state.get("shared_prepare_ms", 0)),
        doc_lane_ms=int(final_state.get("doc_lane_ms", 0)),
        kg_lane_ms=int(final_state.get("kg_lane_ms", 0)),
        timing_report=timing_report.model_dump(mode="json"),
        token_summary=unified_token_summary.model_dump(mode="json"),
    )
    await bus.publish(
        UnifiedBuildCompletedEvent(
            subject=subject,
            build_session_id=unified_result.build_session_id,
            doc_count=unified_result.doc_count,
            chunk_count=unified_result.chunk_count,
            new_node_count=unified_result.new_node_count,
            new_edge_count=unified_result.new_edge_count,
            elapsed_ms=unified_result.elapsed_ms,
        )
    )
    logger.info("unified_digest_timing_summary", **timing_report.model_dump(mode="json"))
    logger.info(
        "unified_digest_build_completed",
        subject=subject,
        build_session_id=unified_result.build_session_id,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        doc_count=unified_result.doc_count,
        chunk_count=unified_result.chunk_count,
        new_node_count=unified_result.new_node_count,
        new_edge_count=unified_result.new_edge_count,
        elapsed_ms=unified_result.elapsed_ms,
        total_tokens=unified_token_summary.total_tokens,
    )
    return unified_result

