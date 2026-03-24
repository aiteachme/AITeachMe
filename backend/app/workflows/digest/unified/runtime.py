"""Unified digest runtime entrypoint."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.runtime import run_state_graph
from app.workflows.digest.unified.events import (
    UnifiedBuildCompletedEvent,
    UnifiedBuildFailedEvent,
    UnifiedBuildStartedEvent,
)
from app.workflows.digest.unified.graph import (
    build_unified_digest_graph,
    create_unified_initial_state,
)
from app.workflows.digest.unified.state import UnifiedBuildResult

logger = structlog.get_logger()


async def run_unified_digest_build(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime | None = None,
    event_bus: InProcessEventBus | None = None,
) -> UnifiedBuildResult:
    """Run the top-level unified digest build."""

    bus = event_bus or InProcessEventBus()
    requested_at = requested_at or datetime.now()
    started_at = perf_counter()

    await bus.publish(UnifiedBuildStartedEvent(subject=subject, file_count=len(file_ids)))
    context = WorkflowContext(
        workflow_name="digest.unified",
        subject=subject,
        event_bus=bus,
        metadata={"requested_at": requested_at.isoformat()},
    )
    result = await run_state_graph(
        workflow_name="digest.unified",
        graph_builder=lambda: build_unified_digest_graph(context=context),
        initial_state=create_unified_initial_state(
            subject=subject,
            file_ids=file_ids,
            user_prompt=user_prompt,
            requested_at=requested_at,
        ),
        context=context,
    )

    if result.failed:
        error_message = result.error.detail
        await bus.publish(
            UnifiedBuildFailedEvent(
                subject=subject,
                build_session_id="",
                error_message=error_message,
            )
        )
        return UnifiedBuildResult(
            subject=subject,
            build_session_id="",
            success=False,
            error=error_message,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
        )

    final_state = result.require_value()
    build_session_id = final_state.get("build_session_id", "")
    error_message = final_state.get("error")
    if error_message:
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
            success=False,
            error=error_message,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            shared_prepare_ms=int(final_state.get("shared_prepare_ms", 0)),
            doc_lane_ms=int(final_state.get("doc_lane_ms", 0)),
            kg_lane_ms=int(final_state.get("kg_lane_ms", 0)),
            repair_ms=int(final_state.get("repair_ms", 0)),
            curriculum_ms=int(final_state.get("curriculum_ms", 0)),
        )

    doc_state = final_state.get("doc_state", {})
    kg_state = final_state.get("kg_state", {})
    curriculum_state = final_state.get("curriculum_state", {})
    coverage_report = final_state.get("coverage_report")
    repair_result = final_state.get("repair_result")
    unified_result = UnifiedBuildResult(
        subject=subject,
        build_session_id=build_session_id,
        success=True,
        doc_count=len(doc_state.get("doc_ids", [])),
        doc_ids=list(doc_state.get("doc_ids", [])),
        chunk_count=len(kg_state.get("chunk_ids", [])),
        new_node_count=len(kg_state.get("new_node_ids", [])),
        new_edge_count=len(kg_state.get("new_edge_ids", [])),
        curriculum_ready=bool(curriculum_state and not curriculum_state.get("error")),
        coverage_report=coverage_report,
        repair_applied=bool(repair_result and repair_result.llm_calls_used > 0),
        elapsed_ms=int((perf_counter() - started_at) * 1000),
        shared_prepare_ms=int(final_state.get("shared_prepare_ms", 0)),
        doc_lane_ms=int(final_state.get("doc_lane_ms", 0)),
        kg_lane_ms=int(final_state.get("kg_lane_ms", 0)),
        repair_ms=int(final_state.get("repair_ms", 0)),
        curriculum_ms=int(final_state.get("curriculum_ms", 0)),
    )
    await bus.publish(
        UnifiedBuildCompletedEvent(
            subject=subject,
            build_session_id=unified_result.build_session_id,
            doc_count=unified_result.doc_count,
            chunk_count=unified_result.chunk_count,
            new_node_count=unified_result.new_node_count,
            new_edge_count=unified_result.new_edge_count,
            curriculum_ready=unified_result.curriculum_ready,
            elapsed_ms=unified_result.elapsed_ms,
        )
    )
    logger.info(
        "unified_digest_build_completed",
        subject=subject,
        build_session_id=unified_result.build_session_id,
        doc_count=unified_result.doc_count,
        chunk_count=unified_result.chunk_count,
        new_node_count=unified_result.new_node_count,
        new_edge_count=unified_result.new_edge_count,
        curriculum_ready=unified_result.curriculum_ready,
        elapsed_ms=unified_result.elapsed_ms,
    )
    return unified_result
