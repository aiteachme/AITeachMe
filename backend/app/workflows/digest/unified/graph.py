"""Top-level LangGraph for unified digest builds."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.shared.infra.config import get_settings
from app.utils.docgen_store import update_knowledge_build_status
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowResult
from app.workflows.digest.docgen.lib.publish import publish_staged_knowledge_docs
from app.workflows.digest.application.runtime import (
    run_docgen_workflow,
    run_graph_digest_workflow,
)
from app.workflows.digest.common.prepare import prepare_shared_inputs
from app.workflows.digest.common.models import DigestMode
from app.workflows.digest.unified.materialize import materialize_shared_inputs
from app.workflows.digest.unified.session import (
    create_unified_build_session,
    pop_unified_build_session,
)
from app.workflows.digest.unified.state import UnifiedDigestState


def build_unified_digest_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the unified digest graph."""

    workflow = StateGraph(UnifiedDigestState)
    trace = workflow_tracer(context=context, lane="unified")
    workflow.add_node(
        "prepare_shared",
        trace.node(
            build_prepare_shared_node(context=context),
            name="prepare_shared",
        ),
    )
    workflow.add_node(
        "run_parallel_lanes",
        trace.node(
            build_parallel_lanes_node(context=context),
            name="run_parallel_lanes",
            timing_field="parallel_lanes_ms",
        ),
    )
    workflow.add_node(
        "publish_outputs",
        trace.node(
            build_publish_outputs_node(context=context),
            name="publish_outputs",
            timing_field="publish_ms",
        ),
    )
    workflow.add_node(
        "cleanup",
        trace.node(
            build_cleanup_node(context=context),
            name="cleanup",
            timing_field="cleanup_ms",
        ),
    )
    workflow.add_node(
        "fail",
        trace.node(
            build_fail_node(context=context),
            name="fail",
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
        {"continue": "publish_outputs", "publish_only": "publish_outputs", "fail": "fail"},
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
    confirmed_plan: dict | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
    tone: str | None = None,
) -> UnifiedDigestState:
    """Create initial state for the unified digest graph."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": build_session_id or uuid4().hex,
        "planner_session_id": planner_session_id or "",
        "confirmed_plan_id": confirmed_plan_id or "",
        "confirmed_plan": confirmed_plan,
        "digest_mode": digest_mode or "",
        "tone": tone or "",
        "graph_job_id": _new_runtime_job_id(),
        "error": None,
    }


def route_after_step(state: UnifiedDigestState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_parallel_lanes(state: UnifiedDigestState) -> str:
    if state.get("error"):
        return "fail"
    if not _graph_is_ready(state.get("kg_state")):
        return "publish_only"
    return "continue"


def _graph_is_ready(kg_state: dict | None) -> bool:
    return bool(kg_state and kg_state.get("graph_ready"))


def _build_kg_doc_chapter_metadatas(doc_state: dict[str, object]) -> list[dict[str, object]]:
    chapter_metadatas = doc_state.get("chapter_metadatas", [])
    if not isinstance(chapter_metadatas, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in chapter_metadatas:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def build_prepare_shared_node(*, context: WorkflowContext):
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
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            error_message=None,
        )
        shared_inputs = await prepare_shared_inputs(
            subject,
            file_ids,
            user_prompt=state.get("user_prompt"),
        )
        if not shared_inputs.source_packets or not shared_inputs.section_packets:
            return {**state, "error": "No shared digest inputs were produced."}

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        if digest_mode:
            try:
                shared_inputs.digest_mode_decision.mode = DigestMode(digest_mode)
            except ValueError:
                digest_mode = shared_inputs.digest_mode_decision.mode.value
            else:
                shared_inputs.digest_mode_decision.reason = "confirmed_build_plan"
                shared_inputs.digest_mode_decision.user_override = True
        tone = state.get("tone") or "encouraging"

        update_knowledge_build_status(
            subject,
            requested_at=state["requested_at"],
            status="running",
            stage="prepare_shared",
            build_session_id=state["build_session_id"],
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            error_message=None,
            digest_mode=digest_mode,
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
            "digest_mode": digest_mode,
            "tone": tone,
            "shared_prepare_ms": elapsed_ms,
        }

    return prepare_shared_node


def build_parallel_lanes_node(*, context: WorkflowContext):
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
            graph_depends_on_doc_summaries=True,
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
                shared_inputs=state.get("shared_inputs"),
                confirmed_plan=state.get("confirmed_plan"),
                planner_session_id=state.get("planner_session_id"),
                confirmed_plan_id=state.get("confirmed_plan_id"),
                digest_mode=state.get("digest_mode"),
                tone=state.get("tone"),
            )
            return result, int((perf_counter() - started_at) * 1000)

        async def run_graph_lane(
            *,
            chapter_metadatas: list[dict[str, object]],
        ) -> tuple[WorkflowResult[dict], int]:
            started_at = perf_counter()
            result = await run_graph_digest_workflow(
                subject=subject,
                job_id=graph_job_id,
                file_ids=file_ids,
                doc_chapter_metadatas=chapter_metadatas,
                event_bus=context.event_bus,
                build_session_id=build_session_id,
            )
            return result, int((perf_counter() - started_at) * 1000)

        doc_state: dict = {}
        errors: list[str] = []
        doc_result, doc_lane_ms = await run_doc_lane()
        if doc_result.failed:
            errors.append(f"Doc lane failed: {doc_result.error.detail}")
        else:
            doc_state = doc_result.require_value()

        chapter_metadatas = _build_kg_doc_chapter_metadatas(doc_state)
        kg_result, kg_lane_ms = await run_graph_lane(chapter_metadatas=chapter_metadatas)

        kg_state: dict = {}
        if kg_result.failed:
            errors.append(f"Graph lane failed: {kg_result.error.detail}")
        else:
            kg_state = kg_result.require_value()

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
                planner_session_id=state.get("planner_session_id") or None,
                confirmed_plan_id=state.get("confirmed_plan_id") or None,
                digest_mode=state.get("digest_mode") or None,
                error_message=None,
                draft_available=bool(str(doc_state.get("merged_markdown", "")).strip()),
                staged_chapter_count=len(doc_state.get("chapter_metadatas", [])),
            )
        return {
            **state,
            "doc_state": doc_state,
            "kg_state": kg_state,
            "graph_ready": _graph_is_ready(kg_state),
            "lane_ms": doc_lane_ms + kg_lane_ms,
            "doc_lane_ms": doc_lane_ms,
            "kg_lane_ms": kg_lane_ms,
            "doc_lane_error": doc_result.error.detail if doc_result.failed else None,
            "kg_lane_error": kg_result.error.detail if kg_result.failed else None,
        }

    return parallel_lanes_node


def build_publish_outputs_node(*, context: WorkflowContext):
    async def publish_outputs_node(state: UnifiedDigestState) -> UnifiedDigestState:
        started_at = perf_counter()
        logger = context.get_logger().bind(node="publish_outputs")
        doc_state = state.get("doc_state", {})

        chapter_metadatas = list(doc_state.get("chapter_metadatas", []))
        if not chapter_metadatas:
            logger.warning("unified_publish_no_docs_to_publish")
            return state

        logger.info(
            "unified_publish_started",
            chapter_count=len(chapter_metadatas),
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="publishing",
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            digest_mode=state.get("digest_mode") or None,
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
            version_no=1,
            build_session_id=state.get("build_session_id"),
        )
        logger.info(
            "unified_publish_completed",
            chapter_count=len(chapter_metadatas),
            doc_count=len(doc_ids),
            elapsed_ms=int((perf_counter() - started_at) * 1000),
        )
        return {
            **state,
            "doc_state": {**doc_state, "doc_ids": doc_ids},
        }

    return publish_outputs_node


def build_cleanup_node(*, context: WorkflowContext):
    async def cleanup_node(state: UnifiedDigestState) -> UnifiedDigestState:
        build_session_id = state.get("build_session_id", "")
        if build_session_id:
            pop_unified_build_session(build_session_id)
            context.get_logger().bind(node="cleanup").info(
                "unified_session_cleanup_completed",
                build_session_id=build_session_id,
            )
        return state

    return cleanup_node


def build_fail_node(*, context: WorkflowContext):
    async def fail_node(state: UnifiedDigestState) -> UnifiedDigestState:
        build_session_id = state.get("build_session_id", "")
        if build_session_id:
            pop_unified_build_session(build_session_id)
        context.get_logger().bind(node="fail").error(
            "unified_build_failed_state",
            error=state.get("error"),
            build_session_id=build_session_id,
        )
        return state

    return fail_node


def _new_runtime_job_id() -> int:
    return (uuid4().int % 2_000_000_000) + 1


def get_langgraph_dev_unified_graph() -> StateGraph:
    """Create the unified digest graph used by ``langgraph dev``."""

    return build_unified_digest_graph(
        context=create_langgraph_dev_context("digest.unified.langgraph_dev"),
    )

