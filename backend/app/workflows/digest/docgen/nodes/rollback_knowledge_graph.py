"""Rollback pre-publish DocGen KG draft rows when document publish does not complete."""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.shared.infra.knowledge.build_store import managed_knowledge_build_owner_transaction
from app.shared.infra.storage import build_course_storage_scope
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import rollback_docgen_kg_draft_graph_early

logger = structlog.get_logger()


def _positive_ints(value: object) -> list[int]:
    items = value if isinstance(value, list) else []
    parsed: list[int] = []
    for item in items:
        try:
            candidate = int(item or 0)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            parsed.append(candidate)
    return parsed


def build_rollback_knowledge_graph_node(*, context: WorkflowContext):
    """Build a failure-only cleanup node for query-visible pre-publish KG draft rows."""

    async def rollback_knowledge_graph_node(state: DocGenState) -> dict[str, object]:
        started_at = perf_counter()
        course_id = state["course_id"]
        build_group_id = str(state.get("build_group_id") or "").strip()
        user_id = str(state.get("user_id") or "").strip()
        course_scope = build_course_storage_scope(user_id=user_id, course_id=course_id) if user_id else None
        build_session_id = str(state.get("build_session_id") or "").strip()
        doc_ids = _positive_ints(state.get("doc_ids"))
        metrics = dict(state.get("kg_draft_early_persist_metrics") or {})
        error = str(state.get("error") or "").strip()

        if doc_ids:
            if state.get("cancel_after_rollback"):
                raise asyncio.CancelledError
            return {
                "kg_draft_rollback_metrics": {
                    "ok": True,
                    "skipped": True,
                    "skip_reason": "document_already_published",
                },
                "kg_draft_rollback_ms": int((perf_counter() - started_at) * 1000),
            }

        try:
            with managed_knowledge_build_owner_transaction(
                course_id,
                build_group_id=build_group_id,
                allowed_phases=("active", "publishing_claimed"),
                allow_cancel_requested=True,
                course_scope=course_scope,
                ownership_error="knowledge_build_rollback_owner_lost",
            ) as session:
                publish_receipt_exists = bool(
                    build_session_id
                    and any(
                        str(doc.build_session_id or "").strip() == build_session_id
                        for doc in get_current_published_docs(session, course_id)
                    )
                )
                if publish_receipt_exists:
                    rollback_metrics = {
                        "ok": True,
                        "skipped": True,
                        "skip_reason": "document_already_published",
                    }
                else:
                    rollback_metrics = rollback_docgen_kg_draft_graph_early(
                        session,
                        course_id=course_id,
                        early_persist_metrics=metrics,
                        reason=error or "docgen_failed_before_publish",
                    )
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "knowledge_build_rollback_owner_lost":
                logger.info(
                    "docgen_kg_draft_rollback_owner_lost",
                    course_id=course_id,
                    build_group_id=build_group_id,
                )
                rollback_metrics = {
                    "ok": True,
                    "skipped": True,
                    "skip_reason": "rollback_owner_lost",
                }
            else:
                logger.warning(
                    "docgen_kg_draft_rollback_failed",
                    course_id=course_id,
                    build_session_id=build_session_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                rollback_metrics = {
                    "ok": False,
                    "skipped": True,
                    "skip_reason": "rollback_failed",
                    "error": str(exc),
                }

        if not rollback_metrics.get("skipped"):
            publish_workflow_stream_event(
                course_id,
                "graph_delta",
                {
                    "stage": "prepare_knowledge_graph_rollback",
                    "build_revision_no": int(rollback_metrics.get("build_revision_no", 0) or 0),
                    "deleted_unit_count": int(rollback_metrics.get("deleted_unit_count", 0) or 0),
                    "restored_unit_count": int(rollback_metrics.get("restored_unit_count", 0) or 0),
                    "deleted_edge_count": int(rollback_metrics.get("deleted_edge_count", 0) or 0),
                    "restored_edge_count": int(rollback_metrics.get("restored_edge_count", 0) or 0),
                    "emitted_at": utcnow().isoformat(),
                },
            )

        context.get_logger().bind(node="rollback_knowledge_graph").info(
            "docgen_kg_draft_rollback_completed",
            **{
                key: value
                for key, value in rollback_metrics.items()
                if key.endswith("_count") or key in {"skipped", "skip_reason", "build_revision_no"}
            },
        )
        if state.get("cancel_after_rollback"):
            raise asyncio.CancelledError
        return {
            "kg_draft_rollback_metrics": rollback_metrics,
            "kg_draft_rollback_ms": int((perf_counter() - started_at) * 1000),
        }

    return rollback_knowledge_graph_node


__all__ = ["build_rollback_knowledge_graph_node"]
