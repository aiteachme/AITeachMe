"""Finalize and failure nodes for the digest graph workflow.

Reads DB: pending graph entities for the active run and current curriculum structures used
by downstream impact analysis.
Writes DB: graph activation / cleanup on ``knowledge_node`` / ``knowledge_edge`` /
revision / evidence tables.
Writes DB (compatibility no-op): graph / curriculum job helpers and build-lock helpers remain
callable, but no dedicated ``graph_digest_job`` / ``curriculum_derive_job`` / lock table is
persisted now.
Writes FS: none.
Idempotency: finalize/fail rewrites the active job outcome and cleans the same pending rows.
"""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
import uuid

from app.core.database import managed_session
from app.repositories import kg_repo
from app.utils.job_helpers import (
    activate_graph_entities_by_job,
    cleanup_pending_by_job,
    update_job_progress,
)
from app.workflows.common.result import WorkflowResult
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger


def _new_runtime_job_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def build_finalize_graph_node(
    *,
    trigger_curriculum_derive: Callable[..., Awaitable[None]],
):
    """Build the finalize node with an injected curriculum trigger."""

    async def finalize_graph_node(state: KGDigestState) -> KGDigestState:
        with managed_session() as session:
            digest_logger = workflow_logger(state)
            try:
                job_id = state["job_id"]
                subject = state["subject"]

                activated = activate_graph_entities_by_job(
                    session,
                    job_id=job_id,
                    subject=subject,
                )
                digest_logger.info(
                    "kg_workflow_activated",
                    activated=activated,
                    chunk_count=len(state.get("chunk_ids", [])),
                    candidate_result_count=len(state.get("candidates", [])),
                    impact_available=state.get("impact_set") is not None,
                )

                kg_repo.release_subject_build_lock(session, subject)

                curriculum_job_id = _new_runtime_job_id()

                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="completed",
                    curriculum_job_id=curriculum_job_id,
                )
                update_job_progress(
                    session,
                    job_id=job_id,
                    job_type="graph",
                    progress=100,
                    current_step="finalize_graph",
                )

                digest_logger.info(
                    "kg_workflow_finalize_complete",
                    curriculum_job_id=curriculum_job_id,
                    chunk_count=len(state.get("chunk_ids", [])),
                    candidate_result_count=len(state.get("candidates", [])),
                    edge_candidate_count=len(state.get("all_candidate_edges", [])),
                )

                asyncio.create_task(
                    trigger_curriculum_derive(
                        subject=subject,
                        graph_job_id=job_id,
                        curriculum_job_id=curriculum_job_id,
                        impact_set=state.get("impact_set"),
                    )
                )
                return {**state, "error": None}
            except Exception as exc:
                session.rollback()
                digest_logger.error("kg_workflow_finalize_failed", error=str(exc), exc_info=True)
                return {**state, "error": f"finalize_failed: {exc}"}

    return finalize_graph_node


async def fail_node(state: KGDigestState) -> KGDigestState:
    """Clean up pending graph data and mark the job as failed."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["job_id"]
            error_message = state.get("error", "unknown_error")

            cleanup_pending_by_job(
                session,
                job_id=job_id,
                job_type="graph",
                subject=state["subject"],
            )
            if state.get("lock_acquired", False):
                kg_repo.release_subject_build_lock(session, state["subject"])

            kg_repo.update_digest_job(
                session,
                job_id,
                status="failed",
                error_message=error_message,
                current_step=_resolve_failure_step(error_message),
            )
            digest_logger.error(
                "kg_workflow_failed",
                error=error_message,
                lock_acquired=state.get("lock_acquired", False),
                chunk_count=len(state.get("chunk_ids", [])),
            )
            return state
        except Exception as exc:
            digest_logger.error("kg_workflow_fail_node_error", error=str(exc), exc_info=True)
            return state


def _resolve_failure_step(error_message: str) -> str:
    if error_message.startswith("prepare_failed:"):
        return "prepare_failed"
    if error_message.startswith("extract_failed:"):
        return "extract_failed"
    if error_message.startswith("cluster_failed:"):
        return "cluster_failed"
    if error_message.startswith("resolve_nodes_failed:"):
        return "resolve_nodes_failed"
    if error_message.startswith("resolve_edges_failed:"):
        return "resolve_edges_failed"
    if error_message.startswith("analyze_impact_failed:"):
        return "analyze_impact_failed"
    if error_message.startswith("finalize_failed:"):
        return "finalize_failed"
    if error_message == "lock_conflict":
        return "acquire_lock_failed"
    if error_message == "no_ready_digest_inputs":
        return "prepare_failed"
    return "failed"


async def trigger_curriculum_derive_safe(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: object | None,
    run_curriculum_derive_workflow: Callable[..., Awaitable[WorkflowResult[object]]],
) -> None:
    """Run curriculum derive in the background."""

    try:
        result = await run_curriculum_derive_workflow(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
        )
        if result.failed:
            workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).error(
                "curriculum_derive_auto_trigger_failed_result",
                curriculum_job_id=curriculum_job_id,
                error=result.error.detail,
            )
    except Exception:
        workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).exception(
            "curriculum_derive_auto_trigger_failed",
            curriculum_job_id=curriculum_job_id,
        )
        workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).error(
            "curriculum_derive_auto_trigger_failed_traceback",
            error=traceback.format_exc()[-500:],
        )


__all__ = [
    "build_finalize_graph_node",
    "fail_node",
    "trigger_curriculum_derive_safe",
]
