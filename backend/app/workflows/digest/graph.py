"""Digest workflow runtime entrypoints."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.digest.curriculum.graph import (
    build_curriculum_derive_graph,
    create_curriculum_derive_initial_state,
)
from app.workflows.digest.events import (
    CurriculumDeriveCompletedEvent,
    CurriculumDeriveFailedEvent,
    DigestBuildRequestedEvent,
    DigestGraphCompletedEvent,
    DigestGraphFailedEvent,
)
from app.workflows.digest.kg.finalize_nodes import trigger_curriculum_derive_safe
from app.workflows.digest.kg.graph import build_kg_digest_graph, create_graph_digest_initial_state
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.state import CurriculumDeriveState, KGDigestState


async def run_graph_digest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[KGDigestState]:
    """Run the digest graph workflow."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(DigestBuildRequestedEvent(subject=subject, job_id=job_id, file_ids=file_ids))

    async def trigger_curriculum_derive(
        *,
        subject: str,
        graph_job_id: int,
        curriculum_job_id: int,
        impact_set: ImpactSet | None,
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
        )

    context = WorkflowContext(
        workflow_name="digest.graph",
        subject=subject,
        event_bus=bus,
        metadata={"job_id": job_id},
    )
    result = await run_state_graph(
        workflow_name="digest.graph",
        graph_builder=lambda: build_kg_digest_graph(
            trigger_curriculum_derive=trigger_curriculum_derive,
        ),
        initial_state=create_graph_digest_initial_state(subject=subject, file_ids=file_ids, job_id=job_id),
        context=context,
    )
    if result.failed:
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
) -> WorkflowResult[CurriculumDeriveState]:
    """Run the digest curriculum workflow."""

    bus = event_bus or InProcessEventBus()
    context = WorkflowContext(
        workflow_name="digest.curriculum",
        subject=subject,
        event_bus=bus,
        metadata={"graph_job_id": graph_job_id, "curriculum_job_id": curriculum_job_id},
    )
    result = await run_state_graph(
        workflow_name="digest.curriculum",
        graph_builder=build_curriculum_derive_graph,
        initial_state=create_curriculum_derive_initial_state(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
        ),
        context=context,
    )
    if result.failed:
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


__all__ = [
    "build_curriculum_derive_graph",
    "build_kg_digest_graph",
    "create_curriculum_derive_initial_state",
    "create_graph_digest_initial_state",
    "run_curriculum_derive_workflow",
    "run_graph_digest_workflow",
]
