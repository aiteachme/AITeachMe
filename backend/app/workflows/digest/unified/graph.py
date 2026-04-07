"""Top-level LangGraph for unified digest builds.

The unified build orchestrates three independent lanes:

1. **docgen lane** — raw_markdowns → knowledge_markdowns (self-contained)
2. **kg lane** — raw_markdowns → knowledge graph (self-contained)
3. **curriculum lane** — knowledge graph → curriculum tree (depends on KG only)

The docgen lane and KG lane run **in parallel** but have **no cross-dependencies**.
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.shared.infra.config import get_settings
from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.common.result import WorkflowResult
from app.workflows.digest.docgen.publish import (
    publish_staged_knowledge_docs,
)
from app.workflows.digest.runtime import (
    run_curriculum_derive_workflow,
    run_docgen_workflow,
    run_graph_digest_workflow,
)
from app.workflows.digest.observability import wrap_digest_node
from app.workflows.digest.shared.prepare import prepare_shared_inputs
from app.workflows.digest.unified.materialize import materialize_shared_inputs
from app.workflows.digest.unified.session import (
    create_unified_build_session,
    pop_unified_build_session,
)
from app.workflows.digest.unified.state import UnifiedDigestState
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


def build_unified_digest_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the unified digest graph.

    Flow:
        prepare_shared → run_parallel_lanes → derive_curriculum → publish_outputs → cleanup
                                                                     ↘ fail
    The docs and KG lanes run in parallel without cross-dependencies.
    After both finish, curriculum is derived from KG only.
    publish_outputs publishes docs from the docgen lane as-is (no overwrite).
    """

    workflow = StateGraph(UnifiedDigestState)
    workflow.add_node(
        "prepare_shared",
        wrap_digest_node(
            build_prepare_shared_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="prepare_shared",
        ),
    )
    workflow.add_node(
        "run_parallel_lanes",
        wrap_digest_node(
            build_parallel_lanes_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="run_parallel_lanes",
            timing_field="parallel_lanes_ms",
        ),
    )
    workflow.add_node(
        "derive_curriculum",
        wrap_digest_node(
            build_derive_curriculum_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="derive_curriculum",
        ),
    )
    workflow.add_node(
        "publish_outputs",
        wrap_digest_node(
            build_publish_outputs_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="publish_outputs",
            timing_field="publish_ms",
        ),
    )
    workflow.add_node(
        "cleanup",
        wrap_digest_node(
            build_cleanup_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="cleanup",
            timing_field="cleanup_ms",
        ),
    )
    workflow.add_node(
        "fail",
        wrap_digest_node(
            build_fail_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="fail",
        ),
    )

    workflow.set_entry_point("prepare_shared")
    workflow.add_conditional_edges(
        "prepare_shared",
        route_after_step,
        {"continue": "run_parallel_lanes", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "run_parallel_lanes",
        route_after_parallel_lanes,
        {"continue": "derive_curriculum", "publish_only": "publish_outputs", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "derive_curriculum",
        route_after_step,
        {"continue": "publish_outputs", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "publish_outputs",
        route_after_step,
        {"continue": "cleanup", "fail": "fail"},
    )
    workflow.add_edge("cleanup", END)
    workflow.add_edge("fail", END)
    return workflow


def create_unified_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None,
    requested_at,
    build_session_id: str | None = None,
) -> UnifiedDigestState:
    """Create initial state for the unified digest graph."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": build_session_id or uuid4().hex,
        "graph_job_id": _new_runtime_job_id(),
        "curriculum_job_id": _new_runtime_job_id(),
        "error": None,
    }


def route_after_step(state: UnifiedDigestState) -> str:
    """Route to the next node or fail."""

    return "fail" if state.get("error") else "continue"


def route_after_parallel_lanes(state: UnifiedDigestState) -> str:
    """Route after parallel lanes.

    If KG lane failed but docs succeeded, skip curriculum and go straight to
    publish (docs-only output). If both failed, fail.
    """

    if state.get("error"):
        return "fail"
    kg_state = state.get("kg_state")
    if not _graph_is_ready(kg_state):
        # KG not ready — skip curriculum, but still publish docs
        return "publish_only"
    return "continue"


def _topic_anchor_count(kg_state: dict | None) -> int:
    if not kg_state:
        return 0
    snapshot = kg_state.get("topic_anchor_snapshot")
    anchors = getattr(snapshot, "anchors", None)
    return len(anchors or [])


def _graph_is_ready(kg_state: dict | None) -> bool:
    if not kg_state:
        return False
    return bool(kg_state.get("graph_ready")) and _topic_anchor_count(kg_state) > 0


def _curriculum_is_ready(curriculum_state: dict | None) -> bool:
    if not curriculum_state:
        return False
    return bool(curriculum_state.get("curriculum_ready")) and curriculum_state.get("snapshot_id") is not None


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------


def build_prepare_shared_node(*, context: WorkflowContext):
    """Prepare shared inputs and canonical chunks."""

    async def prepare_shared_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="prepare_shared")
        subject = state["subject"]
        file_ids = state["file_ids"]
        logger.info("unified_prepare_shared_started", subject=subject, file_count=len(file_ids))
        update_knowledge_build_status(
            subject,
            requested_at=state["requested_at"],
            status="running",
            stage="prepare_shared",
            build_session_id=state["build_session_id"],
            error_message=None,
        )
        shared_inputs = await prepare_shared_inputs(
            subject,
            file_ids,
            user_prompt=state.get("user_prompt"),
        )
        if not shared_inputs.source_packets or not shared_inputs.section_packets:
            return {**state, "error": "No shared digest inputs were produced."}
        update_knowledge_build_status(
            subject,
            requested_at=state["requested_at"],
            status="running",
            stage="prepare_shared",
            build_session_id=state["build_session_id"],
            error_message=None,
            digest_mode=shared_inputs.digest_mode_decision.mode.value,
            mode_reason=shared_inputs.digest_mode_decision.reason,
            total_chunks=len(shared_inputs.section_packets),
            processed_chunks=0,
            current_chunk=0,
        )

        materialized = await materialize_shared_inputs(
            subject=subject,
            shared_inputs=shared_inputs,
            build_session_id=state["build_session_id"],
        )
        session = create_unified_build_session(
            subject=subject,
            file_ids=file_ids,
            shared_inputs=shared_inputs,
            materialized=materialized,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "unified_prepare_shared_completed",
            build_session_id=session.build_session_id,
            source_count=len(shared_inputs.source_packets),
            section_count=len(shared_inputs.section_packets),
            chunk_count=len(materialized.chunk_ids),
            elapsed_ms=elapsed_ms,
        )
        return {
            **state,
            "build_session_id": session.build_session_id,
            "shared_inputs": shared_inputs,
            "materialized": materialized,
            "shared_prepare_ms": elapsed_ms,
        }

    return prepare_shared_node


def build_parallel_lanes_node(*, context: WorkflowContext):
    """Run docs and KG lanes concurrently — no cross-dependencies."""

    async def parallel_lanes_node(state: UnifiedDigestState) -> UnifiedDigestState:
        logger = context.get_logger().bind(node="run_parallel_lanes")
        subject = state["subject"]
        file_ids = state["file_ids"]
        requested_at = state["requested_at"]
        user_prompt = state.get("user_prompt")
        build_session_id = state["build_session_id"]
        graph_job_id = state["graph_job_id"]
        settings = get_settings()

        logger.info(
            "unified_parallel_lanes_started",
            build_session_id=build_session_id,
            file_count=len(file_ids),
            llm_concurrency_limit=settings.llm_concurrency_limit,
            docgen_max_parallel_chapters=settings.docgen_max_parallel_chapters,
        )

        # ----- docgen lane (independent) -----
        async def run_doc_lane() -> tuple[WorkflowResult[dict], int]:
            started_at = perf_counter()
            result = await run_docgen_workflow(
                subject=subject,
                file_ids=file_ids,
                user_prompt=user_prompt,
                requested_at=requested_at,
                event_bus=context.event_bus,
                build_session_id=build_session_id,
            )
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            return result, elapsed_ms

        # ----- KG lane (independent) -----
        async def run_graph_lane() -> tuple[WorkflowResult[dict], int]:
            started_at = perf_counter()
            result = await run_graph_digest_workflow(
                subject=subject,
                job_id=graph_job_id,
                file_ids=file_ids,
                event_bus=context.event_bus,
                build_session_id=build_session_id,
                trigger_curriculum_after_finalize=False,
            )
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            return result, elapsed_ms

        (doc_result, doc_lane_ms), (kg_result, kg_lane_ms) = await asyncio.gather(
            run_doc_lane(),
            run_graph_lane(),
        )

        # Docs and KG are independent — each can succeed/fail independently
        doc_state: dict = {}
        kg_state: dict = {}
        errors: list[str] = []

        if doc_result.failed:
            errors.append(f"Doc lane failed: {doc_result.error.detail}")
        else:
            doc_state = doc_result.require_value()

        if kg_result.failed:
            errors.append(f"Graph lane failed: {kg_result.error.detail}")
        else:
            kg_state = kg_result.require_value()

        # If BOTH failed, report error
        if doc_result.failed and kg_result.failed:
            return {**state, "error": " | ".join(errors)}

        logger.info(
            "unified_parallel_lanes_completed",
            build_session_id=build_session_id,
            doc_lane_ms=doc_lane_ms,
            kg_lane_ms=kg_lane_ms,
            doc_lane_ok=not doc_result.failed,
            kg_lane_ok=not kg_result.failed,
            staged_chapter_count=len(doc_state.get("chapter_metadatas", [])),
            draft_available=bool(str(doc_state.get("merged_markdown", "")).strip()),
            published_doc_count=len(doc_state.get("doc_ids", [])),
            chunk_count=len(kg_state.get("chunk_ids", [])),
        )
        if _graph_is_ready(kg_state):
            update_knowledge_build_status(
                subject,
                requested_at=requested_at,
                status="running",
                stage="graph_ready",
                error_message=None,
                draft_available=bool(str(doc_state.get("merged_markdown", "")).strip()),
                staged_chapter_count=len(doc_state.get("chapter_metadatas", [])),
            )
        return {
            **state,
            "doc_state": doc_state,
            "kg_state": kg_state,
            "graph_ready": _graph_is_ready(kg_state),
            "lane_ms": max(doc_lane_ms, kg_lane_ms),
            "doc_lane_ms": doc_lane_ms,
            "kg_lane_ms": kg_lane_ms,
            "doc_lane_error": doc_result.error.detail if doc_result.failed else None,
            "kg_lane_error": kg_result.error.detail if kg_result.failed else None,
        }

    return parallel_lanes_node


def build_derive_curriculum_node(*, context: WorkflowContext):
    """Run curriculum derivation from KG output (docs-independent)."""

    async def derive_curriculum_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="derive_curriculum")
        kg_state = state.get("kg_state")
        if kg_state is None:
            return {**state, "error": "Unified curriculum missing graph state."}
        if not _graph_is_ready(kg_state):
            return {**state, "error": "Unified curriculum blocked: graph output is empty."}

        logger.info(
            "unified_curriculum_started",
            curriculum_job_id=state["curriculum_job_id"],
            graph_job_id=state["graph_job_id"],
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="curriculum_deriving",
            error_message=None,
        )
        curriculum_result = await run_curriculum_derive_workflow(
            subject=state["subject"],
            graph_job_id=state["graph_job_id"],
            curriculum_job_id=state["curriculum_job_id"],
            event_bus=context.event_bus,
            impact_set=kg_state.get("impact_set"),
            build_session_id=state.get("build_session_id"),
        )
        if curriculum_result.failed:
            # Curriculum failure is non-fatal — docs are already published
            logger.warning(
                "unified_curriculum_failed_non_fatal",
                error=curriculum_result.error.detail,
            )
            return {
                **state,
                "curriculum_state": {},
                "curriculum_ms": int((perf_counter() - started_at) * 1000),
            }

        curriculum_state = curriculum_result.require_value()
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "unified_curriculum_completed",
            curriculum_job_id=state["curriculum_job_id"],
            snapshot_id=curriculum_state.get("snapshot_id"),
            elapsed_ms=elapsed_ms,
        )
        return {
            **state,
            "curriculum_state": curriculum_state,
            "curriculum_ms": elapsed_ms,
        }

    return derive_curriculum_node


def build_publish_outputs_node(*, context: WorkflowContext):
    """Publish docs from the docgen lane output.

    The docgen lane produces its own chapter content — this node publishes it
    using the curriculum version number if available, **without overwriting**
    the docs content.
    """

    async def publish_outputs_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="publish_outputs")
        doc_state = state.get("doc_state", {})
        curriculum_state = state.get("curriculum_state", {})

        chapter_metadatas = list(doc_state.get("chapter_metadatas", []))
        if not chapter_metadatas:
            # docgen lane may have failed — not a fatal error if KG succeeded
            logger.warning("unified_publish_no_docs_to_publish")
            return state

        version_no = int(curriculum_state.get("curriculum_version_no") or 1)

        logger.info(
            "unified_publish_started",
            chapter_count=len(chapter_metadatas),
            curriculum_version_no=version_no,
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="publishing",
            error_message=None,
            draft_available=bool(str(doc_state.get("merged_markdown", "")).strip()),
            staged_chapter_count=len(chapter_metadatas),
        )
        doc_ids = publish_staged_knowledge_docs(
            subject=state["subject"],
            chapter_metadatas=chapter_metadatas,
            chapter_assignments=list(doc_state.get("chapter_assignments", [])),
            user_prompt=state.get("user_prompt"),
            requested_at=state["requested_at"],
            version_no=version_no,
            build_session_id=state.get("build_session_id"),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "unified_publish_completed",
            chapter_count=len(chapter_metadatas),
            doc_count=len(doc_ids),
            elapsed_ms=elapsed_ms,
        )
        return {
            **state,
            "doc_state": {
                **doc_state,
                "doc_ids": doc_ids,
            },
        }

    return publish_outputs_node


def build_cleanup_node(*, context: WorkflowContext):
    """Drop the in-memory build session after success."""

    async def cleanup_node(state: UnifiedDigestState) -> UnifiedDigestState:
        logger = context.get_logger().bind(node="cleanup")
        build_session_id = state.get("build_session_id", "")
        if build_session_id:
            pop_unified_build_session(build_session_id)
            logger.info("unified_session_cleanup_completed", build_session_id=build_session_id)
        return state

    return cleanup_node


def build_fail_node(*, context: WorkflowContext):
    """Drop the in-memory build session after failure."""

    async def fail_node(state: UnifiedDigestState) -> UnifiedDigestState:
        logger = context.get_logger().bind(node="fail")
        build_session_id = state.get("build_session_id", "")
        if build_session_id:
            pop_unified_build_session(build_session_id)
        logger.error("unified_build_failed_state", error=state.get("error"), build_session_id=build_session_id)
        return state

    return fail_node


def _new_runtime_job_id() -> int:
    return (uuid4().int % 2_000_000_000) + 1


def get_langgraph_dev_unified_graph() -> StateGraph:
    """Create the unified digest graph used by ``langgraph dev``."""

    return build_unified_digest_graph(
        context=create_langgraph_dev_context("digest.unified.langgraph_dev"),
    )
