"""Workflow export definitions shared by digest lanes."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.digest.docgen.graph import (
    NODE_DISPATCH,
    NODE_ENHANCE_CHAPTERS,
    NODE_GENERATE_CHAPTERS,
    NODE_MERGE_REVIEW,
    NODE_PUBLISH,
    build_docgen_graph,
)
from app.workflows.digest.kg_file_ingest.graph import build_kg_digest_graph
from app.workflows.digest.kg_file_ingest.prompts import KG_PROMPTS
from app.workflows.digest.planner.lib.steps import STEP_DISPLAY_NAMES
from app.workflows.digest.planner.graph import get_langgraph_dev_planner_graph

PLANNER_PROMPTS = {
    "planner_prompt": "Build-plan prompt used by the planner lane.",
}

DOCGEN_PROMPTS = {
    "outline_enhance_prompt": "DocGen execution-level outline enhancement prompt.",
    "intent_prompt": "DocGen writing-intent inference prompt.",
    "file_summary_prompt": "DocGen file material summary prompt.",
    "writer_prompt": "Chapter writing prompt used by DocGen.",
    "chapter_critic_prompt": "Bounded chapter rewrite prompt.",
    "mermaid_prompt": "Mindmap rendering prompt used by DocGen.",
}


def _build_docgen_graph_for_export():
    context = WorkflowContext(
        workflow_name="digest.docgen",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=context)


def _build_kg_graph_for_export():
    context = WorkflowContext(
        workflow_name="digest.kg_file_ingest",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_kg_digest_graph(context=context)


_DOCGEN_SEND_EDGES = (
    f"{NODE_DISPATCH} -. Send xN .-> {NODE_GENERATE_CHAPTERS}",
    f"{NODE_GENERATE_CHAPTERS} --> {NODE_ENHANCE_CHAPTERS}",
    f"{NODE_ENHANCE_CHAPTERS} --> {NODE_MERGE_REVIEW}",
    f"{NODE_MERGE_REVIEW} --> {NODE_PUBLISH}",
    f"{NODE_PUBLISH} --> __end__",
)


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="digest_planner",
        title="Digest Planner Workflow",
        description="Planner-first workflow that drafts a confirmed Chinese build plan before DocGen starts.",
        build_graph=get_langgraph_dev_planner_graph,
        node_labels=STEP_DISPLAY_NAMES,
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
        build_graph=_build_kg_graph_for_export,
        prompts=KG_PROMPTS,
    ),
)


__all__ = ["WORKFLOW_EXPORTS"]
