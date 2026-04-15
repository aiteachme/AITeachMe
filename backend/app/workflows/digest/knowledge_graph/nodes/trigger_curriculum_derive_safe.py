"""Knowledge graph background curriculum trigger helper."""

from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable

from app.shared.infra.workflow.result import WorkflowResult
from app.workflows.digest.knowledge_graph.support import workflow_logger


async def trigger_curriculum_derive_safe(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: object | None,
    build_session_id: str | None,
    run_curriculum_derive_workflow: Callable[..., Awaitable[WorkflowResult[object]]],
) -> None:
    """Run curriculum derive in the background."""

    try:
        result = await run_curriculum_derive_workflow(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
            build_session_id=build_session_id,
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


__all__ = ["trigger_curriculum_derive_safe"]
