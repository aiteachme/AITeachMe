"""Unified digest build runtime coordinator."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from time import perf_counter

import structlog

from app.workflows.common.events import InProcessEventBus
from app.workflows.digest.build.artifacts import publish_artifact
from app.workflows.digest.build.consistency import RepairBudget, bounded_repair, check_consistency
from app.workflows.digest.build.events import (
    UnifiedBuildCompletedEvent,
    UnifiedBuildFailedEvent,
    UnifiedBuildStartedEvent,
)
from app.workflows.digest.build.state import UnifiedBuildResult
from app.workflows.digest.runtime import run_docgen_workflow, run_graph_digest_workflow
from app.workflows.digest.shared import prepare_shared_inputs

logger = structlog.get_logger()


async def run_unified_digest_build(
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime | None = None,
    event_bus: InProcessEventBus | None = None,
) -> UnifiedBuildResult:
    """Run a single coordinated build for docs and graph without adding a new API."""

    bus = event_bus or InProcessEventBus()
    started_at = perf_counter()
    requested_at = requested_at or datetime.now()

    logger.info("unified_digest_build_started", subject=subject, file_count=len(file_ids))
    await bus.publish(UnifiedBuildStartedEvent(subject=subject, file_count=len(file_ids)))

    try:
        prepare_start = perf_counter()
        shared_inputs = await prepare_shared_inputs(subject, file_ids)
        prepare_ms = int((perf_counter() - prepare_start) * 1000)

        if not shared_inputs.source_packets:
            error_msg = "没有可用的源文件"
            logger.error("unified_digest_build_failed", reason=error_msg)
            await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
            return UnifiedBuildResult(
                subject=subject,
                success=False,
                error=error_msg,
                shared_prepare_ms=prepare_ms,
            )

        # Publish shared inputs once before both lanes start to avoid races.
        await publish_artifact("shared_inputs", shared_inputs, subject=subject)

        doc_lane_start = perf_counter()
        kg_lane_start = perf_counter()
        doc_task = asyncio.create_task(
            _run_doc_lane(
                subject=subject,
                file_ids=file_ids,
                user_prompt=user_prompt,
                requested_at=requested_at,
                event_bus=bus,
            )
        )
        kg_task = asyncio.create_task(
            _run_kg_lane(
                subject=subject,
                file_ids=file_ids,
                event_bus=bus,
            )
        )

        doc_result, kg_result = await asyncio.gather(doc_task, kg_task, return_exceptions=True)
        doc_lane_ms = int((perf_counter() - doc_lane_start) * 1000)
        kg_lane_ms = int((perf_counter() - kg_lane_start) * 1000)

        if isinstance(doc_result, Exception):
            error_msg = f"Doc lane failed: {doc_result}"
            logger.error("unified_digest_build_doc_failed", error=str(doc_result))
            await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
            return UnifiedBuildResult(
                subject=subject,
                success=False,
                error=error_msg,
                shared_prepare_ms=prepare_ms,
                doc_lane_ms=doc_lane_ms,
            )
        if doc_result.failed:
            error_msg = doc_result.error.detail
            logger.error("unified_digest_build_doc_failed", error=error_msg)
            await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
            return UnifiedBuildResult(
                subject=subject,
                success=False,
                error=error_msg,
                shared_prepare_ms=prepare_ms,
                doc_lane_ms=doc_lane_ms,
            )

        if isinstance(kg_result, Exception):
            error_msg = f"KG lane failed: {kg_result}"
            logger.error("unified_digest_build_kg_failed", error=str(kg_result))
            await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
            return UnifiedBuildResult(
                subject=subject,
                success=False,
                error=error_msg,
                shared_prepare_ms=prepare_ms,
                kg_lane_ms=kg_lane_ms,
            )
        if kg_result.failed:
            error_msg = kg_result.error.detail
            logger.error("unified_digest_build_kg_failed", error=error_msg)
            await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
            return UnifiedBuildResult(
                subject=subject,
                success=False,
                error=error_msg,
                shared_prepare_ms=prepare_ms,
                kg_lane_ms=kg_lane_ms,
            )

        consistency_start = perf_counter()
        coverage_report = await check_consistency(
            doc_result.require_value(),
            kg_result.require_value(),
        )
        consistency_ms = int((perf_counter() - consistency_start) * 1000)

        repair_applied = False
        if coverage_report.has_gaps():
            logger.info("unified_digest_build_repairing", gap_count=coverage_report.gap_count())
            repair_result = await bounded_repair(
                coverage_report,
                budget=RepairBudget(),
            )
            repair_applied = repair_result.llm_calls_used > 0

        doc_state = doc_result.require_value()
        kg_state = kg_result.require_value()
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        result = UnifiedBuildResult(
            subject=subject,
            success=True,
            doc_count=len(doc_state.get("doc_ids", [])),
            doc_ids=doc_state.get("doc_ids", []),
            chunk_count=len(kg_state.get("chunk_ids", [])),
            new_node_count=len(kg_state.get("new_node_ids", [])),
            new_edge_count=len(kg_state.get("new_edge_ids", [])),
            coverage_report=coverage_report,
            repair_applied=repair_applied,
            elapsed_ms=elapsed_ms,
            shared_prepare_ms=prepare_ms,
            doc_lane_ms=doc_lane_ms,
            kg_lane_ms=kg_lane_ms,
            consistency_check_ms=consistency_ms,
        )

        logger.info(
            "unified_digest_build_completed",
            subject=subject,
            doc_count=result.doc_count,
            chunk_count=result.chunk_count,
            new_node_count=result.new_node_count,
            new_edge_count=result.new_edge_count,
            gap_count=coverage_report.gap_count(),
            repair_applied=repair_applied,
            elapsed_ms=elapsed_ms,
        )
        await bus.publish(
            UnifiedBuildCompletedEvent(
                subject=subject,
                doc_count=result.doc_count,
                chunk_count=result.chunk_count,
                new_node_count=result.new_node_count,
                new_edge_count=result.new_edge_count,
                elapsed_ms=elapsed_ms,
            )
        )
        return result
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        error_msg = f"Unified build failed: {exc}"
        logger.exception("unified_digest_build_exception", subject=subject, error=str(exc))
        await bus.publish(UnifiedBuildFailedEvent(subject=subject, error_message=error_msg))
        return UnifiedBuildResult(
            subject=subject,
            success=False,
            error=error_msg,
            elapsed_ms=elapsed_ms,
        )


async def _run_doc_lane(
    subject: str,
    file_ids: list[int],
    user_prompt: str | None,
    requested_at: datetime,
    event_bus: InProcessEventBus,
):
    """Run the doc lane."""

    logger.info("doc_lane_started", subject=subject)
    result = await run_docgen_workflow(
        subject=subject,
        file_ids=file_ids,
        user_prompt=user_prompt,
        requested_at=requested_at,
        event_bus=event_bus,
    )
    logger.info("doc_lane_completed", subject=subject, success=not result.failed)
    return result


async def _run_kg_lane(
    subject: str,
    file_ids: list[int],
    event_bus: InProcessEventBus,
):
    """Run the KG lane."""

    logger.info("kg_lane_started", subject=subject)
    job_id = int(time.time() * 1000) % 1000000
    result = await run_graph_digest_workflow(
        subject=subject,
        job_id=job_id,
        file_ids=file_ids,
        event_bus=event_bus,
    )
    logger.info("kg_lane_completed", subject=subject, success=not result.failed)
    return result
