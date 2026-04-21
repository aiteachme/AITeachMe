"""File-ingest KnowledgeGraph workflow."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.common.events import (
    DigestBuildRequestedEvent,
    DigestGraphCompletedEvent,
    DigestGraphFailedEvent,
)
from app.workflows.digest.common.metrics import build_token_summary
from app.workflows.digest.kg_file_ingest.graph import (
    RUN_NAME_KG_FILE_INGEST,
    build_kg_digest_graph,
    create_graph_digest_initial_state,
)
from app.workflows.digest.kg_file_ingest.lib.reporting import build_kg_lane_summary
from app.workflows.digest.kg_file_ingest.state import KnowledgeDigestState


async def run_graph_file_ingest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
    user_prompt: str | None = None,
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
) -> WorkflowResult[KnowledgeDigestState]:
    bus = event_bus or InProcessEventBus()
    await bus.publish(DigestBuildRequestedEvent(subject=subject, job_id=job_id, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.kg_file_ingest",
        subject=subject,
        event_bus=bus,
        metadata={
            "job_id": job_id,
            "build_session_id": build_session_id or "",
            "lane": "kg_file_ingest",
            "langsmith_run_name": RUN_NAME_KG_FILE_INGEST,
        },
    )
    result = await run_state_graph(
        workflow_name="digest.kg_file_ingest",
        graph_builder=lambda: build_kg_digest_graph(context=context),
        initial_state=create_graph_digest_initial_state(
            subject=subject,
            file_ids=file_ids,
            job_id=job_id,
            build_session_id=build_session_id,
            user_prompt=user_prompt,
            doc_chapter_metadatas=doc_chapter_metadatas,
        ),
        context=context,
    )
    if result.failed:
        token_summary = build_token_summary(build_session_id=build_session_id or None, lane="kg")
        context.get_logger().bind(node="runtime").info(
            "kg_digest_timing_summary",
            **build_kg_lane_summary(
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
    kg_token_summary = build_token_summary(
        build_session_id=final_state.get("build_session_id") or build_session_id or None,
        lane="kg",
    )
    final_state["token_summary"] = kg_token_summary.model_dump()
    final_state["timing_summary"] = build_kg_lane_summary(final_state, token_summary=kg_token_summary)
    context.get_logger().bind(node="runtime").info(
        "kg_digest_timing_summary",
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


__all__ = ["run_graph_file_ingest_workflow"]


