"""Runtime entrypoints for digest workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Awaitable, Callable

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.digest.observability import (
    build_curriculum_lane_summary,
    build_docgen_lane_summary,
    build_kg_lane_summary,
    build_token_summary,
)
from app.workflows.digest.events import (
    CurriculumDeriveCompletedEvent,
    CurriculumDeriveFailedEvent,
    DigestBuildRequestedEvent,
    DigestGraphCompletedEvent,
    DigestGraphFailedEvent,
    DocGenCompletedEvent,
    DocGenFailedEvent,
    DocGenRequestedEvent,
)
from app.workflows.digest.graph import (
    build_curriculum_derive_graph,
    build_docgen_graph,
    build_kg_digest_graph,
    create_curriculum_derive_initial_state,
    create_docgen_initial_state,
    create_graph_digest_initial_state,
)
from app.workflows.digest.kg.finalize_nodes import trigger_curriculum_derive_safe
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.state import CurriculumDeriveState, DocGenState, KGDigestState

CurriculumTrigger = Callable[..., Awaitable[None]]


async def run_graph_digest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
    event_bus: InProcessEventBus | None = None,
    build_session_id: str | None = None,
    trigger_curriculum_after_finalize: bool = True,
) -> WorkflowResult[KGDigestState]:
    """Run the graph lane workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DigestBuildRequestedEvent(subject=subject, job_id=job_id, file_ids=file_ids))

    async def trigger_curriculum_derive(
        *,
        subject: str,
        graph_job_id: int,
        curriculum_job_id: int,
        impact_set: ImpactSet | None,
        build_session_id: str | None,
    ) -> None:
        await trigger_curriculum_derive_safe(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
            run_curriculum_derive_workflow=lambda **kwargs: run_curriculum_derive_workflow(
                event_bus=bus,
                **kwargs,
            ),
            build_session_id=build_session_id,
        )

    async def noop_curriculum_trigger(**_: object) -> None:
        return None

    context = WorkflowContext(
        workflow_name="digest.graph",
        subject=subject,
        event_bus=bus,
        metadata={"job_id": job_id, "build_session_id": build_session_id or ""},
    )
    result = await run_state_graph(
        workflow_name="digest.graph",
        graph_builder=lambda: build_kg_digest_graph(
            trigger_curriculum_derive=(
                trigger_curriculum_derive if trigger_curriculum_after_finalize else noop_curriculum_trigger
            ),
        ),
        initial_state=create_graph_digest_initial_state(
            subject=subject,
            file_ids=file_ids,
            job_id=job_id,
            build_session_id=build_session_id,
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


async def run_curriculum_derive_workflow(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    event_bus: InProcessEventBus | None = None,
    impact_set: ImpactSet | None = None,
    build_session_id: str | None = None,
) -> WorkflowResult[CurriculumDeriveState]:
    """Run the curriculum derive workflow."""

    bus = event_bus or InProcessEventBus()
    context = WorkflowContext(
        workflow_name="digest.curriculum",
        subject=subject,
        event_bus=bus,
        metadata={
            "graph_job_id": graph_job_id,
            "curriculum_job_id": curriculum_job_id,
            "build_session_id": build_session_id or "",
        },
    )
    result = await run_state_graph(
        workflow_name="digest.curriculum",
        graph_builder=build_curriculum_derive_graph,
        initial_state=create_curriculum_derive_initial_state(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
            build_session_id=build_session_id,
        ),
        context=context,
    )
    if result.failed:
        token_summary = build_token_summary(build_session_id=build_session_id or None, lane="curriculum")
        context.get_logger().bind(node="runtime").info(
            "curriculum_timing_summary",
            **build_curriculum_lane_summary(
                {},
                token_summary=token_summary,
                status="failed",
                error_message=result.error.detail,
            ),
        )
        await bus.publish(
            CurriculumDeriveFailedEvent(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    curriculum_token_summary = build_token_summary(
        build_session_id=final_state.get("build_session_id") or build_session_id or None,
        lane="curriculum",
    )
    final_state["token_summary"] = curriculum_token_summary.model_dump()
    final_state["timing_summary"] = build_curriculum_lane_summary(
        final_state,
        token_summary=curriculum_token_summary,
    )
    context.get_logger().bind(node="runtime").info(
        "curriculum_timing_summary",
        **final_state["timing_summary"],
    )
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            CurriculumDeriveFailedEvent(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
                error_message=error_message,
            )
        )
        return err_result(
            "digest_curriculum_failed",
            error_message,
            metadata={"graph_job_id": graph_job_id, "curriculum_job_id": curriculum_job_id},
        )

    await bus.publish(
        CurriculumDeriveCompletedEvent(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
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
) -> WorkflowResult[DocGenState]:
    """Run the docgen lane workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DocGenRequestedEvent(subject=subject, requested_at=requested_at, file_ids=file_ids))

    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject=subject,
        event_bus=bus,
        metadata={
            "requested_at": requested_at.isoformat(),
            "build_session_id": build_session_id or "",
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
    "create_curriculum_derive_initial_state",
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "run_curriculum_derive_workflow",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
]
