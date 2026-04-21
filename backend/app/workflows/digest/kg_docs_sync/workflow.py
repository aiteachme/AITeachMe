"""Knowledge-doc sync workflow."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.kg_docs_sync.graph import (
    RUN_NAME_KG_DOCS_SYNC,
    build_docs_sync_graph,
    create_docs_sync_initial_state,
)
from app.workflows.digest.kg_docs_sync.lib import normalize_docs_sync_inputs
from app.workflows.digest.kg_docs_sync.state import DocsSyncState
from app.workflows.support.knowledge_graph.incremental_sync import KnowledgeSyncReport


async def run_graph_docs_sync_workflow(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
    build_session_id: str | None = None,
) -> WorkflowResult[KnowledgeSyncReport]:
    normalized_subject, normalized_markdown, normalized_revision = normalize_docs_sync_inputs(
        subject=subject,
        markdown=markdown,
        build_revision_no=build_revision_no,
    )
    try:
        context = WorkflowContext(
            workflow_name="digest.kg_docs_sync",
            subject=normalized_subject,
            metadata={
                "build_session_id": build_session_id or "",
                "lane": "kg_docs_sync",
                "langsmith_run_name": RUN_NAME_KG_DOCS_SYNC,
                "build_revision_no": normalized_revision,
            },
        )
        result = await run_state_graph(
            workflow_name="digest.kg_docs_sync",
            graph_builder=lambda: build_docs_sync_graph(context=context),
            initial_state=create_docs_sync_initial_state(
                subject=normalized_subject,
                markdown=normalized_markdown,
                build_revision_no=normalized_revision,
                build_session_id=build_session_id,
            ),
            context=context,
        )
        if result.failed:
            return err_result(
                "digest_graph_docs_sync_failed",
                result.error.detail,
                metadata={"subject": normalized_subject},
            )

        final_state: DocsSyncState = result.require_value()
        report = final_state.get("report")
        if report is None:
            raise RuntimeError(final_state.get("error") or "docs_sync_report_missing")
        if final_state.get("error"):
            return err_result(
                "digest_graph_docs_sync_failed",
                str(final_state.get("error") or "docs_sync_report_missing"),
                metadata={"subject": normalized_subject},
            )
        return ok_result(report)
    except ValueError as exc:
        return err_result(
            "digest_graph_docs_sync_invalid_markdown",
            str(exc),
            metadata={"subject": normalized_subject},
        )
    except Exception as exc:
        return err_result(
            "digest_graph_docs_sync_failed",
            str(exc),
            metadata={"subject": normalized_subject},
        )


__all__ = ["run_graph_docs_sync_workflow"]
