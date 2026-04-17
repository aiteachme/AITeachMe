"""Workflow export definitions shared by digest lanes."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.digest.docgen.graph import build_docgen_graph
from app.workflows.digest.kg_file_ingest.graph import build_kg_digest_graph
from app.workflows.digest.kg_file_ingest.prompts import KG_PROMPTS
from app.workflows.digest.planner.graph import get_langgraph_dev_planner_graph

PLANNER_PROMPTS = {
    "planner_prompt": "Build-plan prompt used by the planner lane.",
}

DOCGEN_PROMPTS = {
    "research_purify_prompt": "Research purification prompt used by docgen.",
    "writer_prompt": "Chapter writing prompt used by docgen.",
    "mermaid_prompt": "Mindmap rendering prompt used by docgen.",
}


def _build_docgen_graph_for_export():
    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=context)


_DOCGEN_SEND_EDGES = (
    "load_context -. Send xN .-> research_chapters",
    "finalize_titles -. Send xN .-> write_chapters",
    "write_chapters --> merge_drafts",
    "merge_drafts --> enrich_assets",
    "enrich_assets --> append_practice",
    "append_practice --> publish_document",
    "publish_document --> __end__",
)


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="digest_planner",
        title="Digest Planner Workflow",
        description="Planner-first workflow that drafts a confirmed Chinese build plan before DocGen starts.",
        build_graph=get_langgraph_dev_planner_graph,
        prompts=PLANNER_PROMPTS,
    ),
    WorkflowGraphExport(
        key="digest_docgen",
        title="Digest DocGen Workflow",
        description="Knowledge document generation workflow with fan-out parallelism.",
        build_graph=_build_docgen_graph_for_export,
        extra_edges=_DOCGEN_SEND_EDGES,
        prompts=DOCGEN_PROMPTS,
    ),
    WorkflowGraphExport(
        key="digest_graph",
        title="Digest Graph Workflow",
        description="Incremental knowledge-graph build workflow.",
        build_graph=build_kg_digest_graph,
        prompts=KG_PROMPTS,
    ),
)


__all__ = ["WORKFLOW_EXPORTS"]
