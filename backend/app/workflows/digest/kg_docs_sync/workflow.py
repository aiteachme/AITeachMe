"""Knowledge-doc sync workflow."""

from __future__ import annotations

from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result
from app.workflows.digest.kg_docs_sync.graph import run_docs_sync_graph
from app.workflows.digest.kg_docs_sync.lib import normalize_docs_sync_inputs
from app.workflows.digest.kg_docs_sync.state import DocsSyncState
from app.workflows.support.knowledge_graph.incremental_sync import KnowledgeSyncReport


def run_graph_docs_sync_workflow(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
) -> WorkflowResult[KnowledgeSyncReport]:
    normalized_subject, normalized_markdown, normalized_revision = normalize_docs_sync_inputs(
        subject=subject,
        markdown=markdown,
        build_revision_no=build_revision_no,
    )
    try:
        state: DocsSyncState = {
            "subject": normalized_subject,
            "markdown": normalized_markdown,
            "build_revision_no": normalized_revision,
        }
        final_state = run_docs_sync_graph(state)
        report = final_state.get("report")
        if report is None:
            raise RuntimeError(final_state.get("error") or "docs_sync_report_missing")
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


