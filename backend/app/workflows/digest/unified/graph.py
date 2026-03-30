"""Top-level LangGraph for unified digest builds."""

from __future__ import annotations

import asyncio
from time import perf_counter
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common.context import WorkflowContext
from app.workflows.common.result import WorkflowResult
from app.workflows.digest.docs.publish import (
    publish_staged_knowledge_docs,
    stage_knowledge_docs,
)
from app.workflows.digest.docs.services.curriculum_book import (
    build_curriculum_aligned_book,
)
from app.workflows.digest.runtime import (
    run_curriculum_derive_workflow,
    run_docgen_workflow,
    run_graph_digest_workflow,
)
from app.workflows.digest.observability import wrap_digest_node
from app.workflows.digest.shared.prepare import prepare_shared_inputs
from app.workflows.digest.unified.consistency import bounded_repair, check_consistency
from app.workflows.digest.unified.materialize import materialize_shared_inputs
from app.workflows.digest.unified.models import RepairBudget, RepairResult
from app.workflows.digest.unified.session import (
    create_unified_build_session,
    pop_unified_build_session,
)
from app.workflows.digest.unified.state import UnifiedDigestState


def build_unified_digest_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the unified digest graph."""

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
        "consistency_gate",
        wrap_digest_node(
            build_consistency_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="consistency_gate",
            timing_field="consistency_ms",
        ),
    )
    workflow.add_node(
        "bounded_repair",
        wrap_digest_node(
            build_repair_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified_repair",
            node_name="bounded_repair",
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
        "rebuild_docs",
        wrap_digest_node(
            build_rebuild_docs_node(context=context),
            workflow_name=context.workflow_name,
            lane="unified",
            node_name="rebuild_docs",
            timing_field="rebuild_docs_ms",
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
        route_after_step,
        {"continue": "consistency_gate", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "consistency_gate",
        route_after_step,
        {"continue": "bounded_repair", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "bounded_repair",
        route_after_step,
        {"continue": "derive_curriculum", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "derive_curriculum",
        route_after_step,
        {"continue": "rebuild_docs", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "rebuild_docs",
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
) -> UnifiedDigestState:
    """Create initial state for the unified digest graph."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": uuid4().hex,
        "graph_job_id": _new_runtime_job_id(),
        "curriculum_job_id": _new_runtime_job_id(),
        "error": None,
    }


def route_after_step(state: UnifiedDigestState) -> str:
    """Route to the next node or fail."""

    return "fail" if state.get("error") else "continue"


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
            error_message=None,
        )
        shared_inputs = await prepare_shared_inputs(
            subject,
            file_ids,
            user_prompt=state.get("user_prompt"),
        )
        if not shared_inputs.source_packets or not shared_inputs.section_packets:
            return {**state, "error": "No shared digest inputs were produced."}

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
    """Run docs and graph lanes concurrently."""

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
        if doc_result.failed:
            return {**state, "error": f"Doc lane failed: {doc_result.error.detail}"}
        if kg_result.failed:
            return {**state, "error": f"Graph lane failed: {kg_result.error.detail}"}

        doc_state = doc_result.require_value()
        kg_state = kg_result.require_value()
        logger.info(
            "unified_parallel_lanes_completed",
            build_session_id=build_session_id,
            doc_lane_ms=doc_lane_ms,
            kg_lane_ms=kg_lane_ms,
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
        }

    return parallel_lanes_node


def build_consistency_node(*, context: WorkflowContext):
    """Run cross-lane consistency checks."""

    async def consistency_node(state: UnifiedDigestState) -> UnifiedDigestState:
        logger = context.get_logger().bind(node="consistency_gate")
        doc_state = state.get("doc_state")
        kg_state = state.get("kg_state")
        if doc_state is None or kg_state is None:
            return {**state, "error": "Unified consistency missing lane results."}
        if not _graph_is_ready(kg_state):
            return {
                **state,
                "error": (
                    "Unified consistency failed: graph lane completed without a usable graph. "
                    f"topic_anchor_count={_topic_anchor_count(kg_state)}"
                ),
            }
        coverage_report = await check_consistency(doc_state, kg_state)
        logger.info(
            "unified_consistency_gate_completed",
            gap_count=coverage_report.gap_count(),
        )
        return {**state, "coverage_report": coverage_report}

    return consistency_node


def build_repair_node(*, context: WorkflowContext):
    """Run bounded repair selection."""

    async def repair_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="bounded_repair")
        coverage_report = state.get("coverage_report")
        if coverage_report is None:
            return {**state, "error": "Unified repair missing coverage report."}
        repair_result = (
            await bounded_repair(coverage_report, RepairBudget())
            if coverage_report.has_gaps()
            else RepairResult()
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "unified_repair_completed",
            repaired_chapter_count=len(repair_result.repaired_chapters),
            reextract_chunk_count=len(repair_result.reextracted_chunks),
            elapsed_ms=elapsed_ms,
        )
        return {
            **state,
            "repair_result": repair_result,
            "repair_ms": elapsed_ms,
        }

    return repair_node


def build_derive_curriculum_node(*, context: WorkflowContext):
    """Run curriculum derivation after both lanes finish."""

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
            return {
                **state,
                "error": f"Curriculum derive failed: {curriculum_result.error.detail}",
            }

        curriculum_state = curriculum_result.require_value()
        if not _curriculum_is_ready(curriculum_state):
            return {
                **state,
                "error": "Curriculum derive completed without a usable curriculum snapshot.",
            }

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


def build_rebuild_docs_node(*, context: WorkflowContext):
    """Rebuild final docs from the published curriculum structure."""

    async def rebuild_docs_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="rebuild_docs")
        doc_state = state.get("doc_state")
        curriculum_state = state.get("curriculum_state")
        shared_inputs = state.get("shared_inputs")
        materialized = state.get("materialized")
        if doc_state is None:
            return {**state, "error": "Unified rebuild missing docs state."}
        if not _curriculum_is_ready(curriculum_state) or curriculum_state.get("theme_tree_version_id") is None:
            return {**state, "error": "Unified rebuild missing a usable curriculum theme tree."}
        if shared_inputs is None or materialized is None:
            return {**state, "error": "Unified rebuild missing shared inputs."}

        theme_tree_version_id = int(curriculum_state["theme_tree_version_id"])
        logger.info(
            "unified_curriculum_book_rebuild_started",
            theme_tree_version_id=theme_tree_version_id,
        )
        chapter_metadatas, chapter_assignments = build_curriculum_aligned_book(
            subject=state["subject"],
            theme_tree_version_id=theme_tree_version_id,
            shared_inputs=shared_inputs,
            materialized=materialized,
        )
        if not chapter_metadatas:
            logger.warning("unified_curriculum_book_rebuild_empty")
            return {**state, "error": "Unified rebuild produced no curriculum-aligned chapters."}

        existing_chapters = list(doc_state.get("chapter_metadatas", []))
        if existing_chapters and len(chapter_metadatas) < len(existing_chapters):
            logger.warning(
                "unified_curriculum_book_rebuild_skipped",
                reason="fewer_chapters_than_doc_lane",
                rebuilt_chapter_count=len(chapter_metadatas),
                doc_lane_chapter_count=len(existing_chapters),
            )
            return state

        staged_docs = await stage_knowledge_docs(
            subject=state["subject"],
            chapter_metadatas=chapter_metadatas,
        )
        existing_merged_markdown = str(doc_state.get("merged_markdown", ""))
        if existing_merged_markdown and len(staged_docs.merged_markdown) < int(len(existing_merged_markdown) * 0.6):
            logger.warning(
                "unified_curriculum_book_rebuild_skipped",
                reason="rebuilt_markdown_too_small",
                rebuilt_chars=len(staged_docs.merged_markdown),
                doc_lane_chars=len(existing_merged_markdown),
            )
            return state

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "unified_curriculum_book_rebuild_completed",
            chapter_count=len(chapter_metadatas),
            merged_chars=len(staged_docs.merged_markdown),
            elapsed_ms=elapsed_ms,
        )
        return {
            **state,
            "doc_state": {
                **doc_state,
                "chapter_metadatas": chapter_metadatas,
                "chapter_assignments": chapter_assignments,
                "merged_markdown": staged_docs.merged_markdown,
                "built_paths": staged_docs.built_paths,
            },
        }

    return rebuild_docs_node


def build_publish_outputs_node(*, context: WorkflowContext):
    """Publish staged docs after graph and curriculum have both succeeded."""

    async def publish_outputs_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="publish_outputs")
        doc_state = state.get("doc_state")
        curriculum_state = state.get("curriculum_state")
        kg_state = state.get("kg_state")
        if doc_state is None:
            return {**state, "error": "Unified publish missing docs state."}
        if not _graph_is_ready(kg_state):
            return {**state, "error": "Unified publish blocked: graph output is empty."}
        if not _curriculum_is_ready(curriculum_state):
            return {**state, "error": "Unified publish missing a usable curriculum snapshot."}

        chapter_metadatas = list(doc_state.get("chapter_metadatas", []))
        if not chapter_metadatas:
            return {**state, "error": "Unified publish missing chapter metadata."}

        logger.info(
            "unified_publish_started",
            chapter_count=len(chapter_metadatas),
            snapshot_id=curriculum_state.get("snapshot_id"),
            curriculum_version_no=curriculum_state.get("curriculum_version_no"),
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
            version_no=int(curriculum_state.get("curriculum_version_no") or 1),
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
