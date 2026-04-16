"""Runtime entrypoints for digest workflows."""

from __future__ import annotations

from datetime import datetime

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.events import (
    DigestBuildRequestedEvent,
    DigestGraphCompletedEvent,
    DigestGraphFailedEvent,
    DocGenCompletedEvent,
    DocGenFailedEvent,
    DocGenRequestedEvent,
)
from app.workflows.digest.graph import (
    build_docgen_graph,
    build_knowledge_digest_graph,
    create_docgen_initial_state,
    create_graph_digest_initial_state,
)
from app.workflows.digest.docgen.lib.reporting import build_docgen_lane_summary
from app.workflows.digest.knowledge_graph.lib.reporting import build_knowledge_lane_summary
from app.workflows.digest.shared.metrics import build_token_summary
from app.workflows.digest.state import DocGenState, KnowledgeDigestState


async def run_graph_digest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
) -> WorkflowResult[KnowledgeDigestState]:
    """Run the graph lane workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DigestBuildRequestedEvent(subject=subject, job_id=job_id, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.graph",
        subject=subject,
        event_bus=bus,
        metadata={"job_id": job_id, "build_session_id": build_session_id or ""},
    )
    result = await run_state_graph(
        workflow_name="digest.graph",
        graph_builder=build_knowledge_digest_graph,
        initial_state=create_graph_digest_initial_state(
            subject=subject,
            file_ids=file_ids,
            job_id=job_id,
            build_session_id=build_session_id,
            doc_chapter_metadatas=doc_chapter_metadatas,
        ),
        context=context,
    )
    if result.failed:
        token_summary = build_token_summary(build_session_id=build_session_id or None, lane="knowledge")
        context.get_logger().bind(node="runtime").info(
            "knowledge_digest_timing_summary",
            **build_knowledge_lane_summary(
                {},
                token_summary=token_summary,
                status="failed",
                error_message=result.error.detail,
            ),
        )
        await bus.publish(
            DigestGraphFailedEvent(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    knowledge_token_summary = build_token_summary(
        build_session_id=final_state.get("build_session_id") or build_session_id or None,
        lane="knowledge",
    )
    final_state["token_summary"] = knowledge_token_summary.model_dump()
    final_state["timing_summary"] = build_knowledge_lane_summary(final_state, token_summary=knowledge_token_summary)
    context.get_logger().bind(node="runtime").info(
        "knowledge_digest_timing_summary",
        **final_state["timing_summary"],
    )
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            DigestGraphFailedEvent(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_graph_failed",
            error_message,
            metadata={"job_id": job_id, "subject": subject},
        )

    await bus.publish(
        DigestGraphCompletedEvent(
            subject=subject,
            job_id=job_id,
            file_ids=file_ids,
            chunk_count=len(final_state.get("chunk_ids", [])),
        )
    )
    return result


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
    tone: str | None = None,
) -> WorkflowResult[DocGenState]:
    """Run the DocGen lane workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DocGenRequestedEvent(subject=subject, requested_at=requested_at, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject=subject,
        event_bus=bus,
        metadata={
            "requested_at": requested_at.isoformat(),
            "build_session_id": build_session_id or "",
            "planner_session_id": planner_session_id or "",
            "confirmed_plan_id": confirmed_plan_id or "",
            "digest_mode": digest_mode or "",
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
            tone=tone,
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
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
]
