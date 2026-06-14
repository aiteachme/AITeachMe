"""Workflow export definitions shared by digest lanes."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.digest.docgen.graph import (
    NODE_ASSEMBLE_CHAPTER_TASKS,
    NODE_DOCUMENT_CONSISTENCY_REVIEW,
    NODE_ENHANCE_CHAPTERS,
    NODE_GENERATE_CHAPTERS,
    NODE_GENERATE_UNIT_TESTS,
    NODE_DISPLAY_NAMES as DOCGEN_NODE_DISPLAY_NAMES,
    NODE_MERGE_REVIEW,
    NODE_PUBLISH,
    NODE_REPAIR_OR_ROUTE,
    NODE_REVIEW_CHAPTERS,
    NODE_SYNC_LOCKED_TITLES,
    NODE_SYNC_KNOWLEDGE_GRAPH,
    build_docgen_graph,
)
from app.workflows.digest.kg_doc_sync.graph import get_langgraph_dev_kg_doc_sync_graph
from app.workflows.digest.planner.lib.steps import STEP_DISPLAY_NAMES
from app.workflows.digest.planner.graph import get_langgraph_dev_planner_graph
from app.workflows.digest.kg_doc_sync.prompts.registry import KG_PROMPTS

PLANNER_PROMPTS = {
    "planner_prompt": "Build-plan prompt used by the planner lane.",
}

DOCGEN_PROMPTS = {
    "intent_core_prompt": "DocGen document-level intent inference prompt.",
    "file_summary_prompt": "DocGen file material summary prompt.",
    "title_lock_prompt": "DocGen chapter title locking prompt.",
    "chapter_execution_brief_prompt": "DocGen chapter execution brief prompt.",
    "query_planning_prompt": "DocGen chapter research query planning prompt.",
    "research_purify_prompt": "DocGen dense-context cleanup prompt.",
    "writer_prompt": "Chapter writing prompt used by DocGen.",
    "heading_repair_prompt": "DocGen chapter heading and scaffold repair prompt.",
    "chapter_rewrite_prompt": "Bounded chapter rewrite prompt.",
    "mermaid_prompt": "Mindmap rendering prompt used by DocGen.",
    "interactive_html_prompt": "DocGen interactive HTML sidecar prompt.",
    "chapter_review_prompt": "DocGen chapter review prompt.",
    "repair_prompt": "DocGen review-action patch prompt.",
}


def _build_docgen_graph_for_export():
    context = WorkflowContext(
        workflow_name="digest.docgen",
        course_id="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=context)


_DOCGEN_SEND_EDGES = (
    f"{NODE_ASSEMBLE_CHAPTER_TASKS} -. Send xN .-> {NODE_GENERATE_CHAPTERS}",
    f"{NODE_GENERATE_CHAPTERS} --> {NODE_GENERATE_UNIT_TESTS}",
    f"{NODE_GENERATE_UNIT_TESTS} --> {NODE_ENHANCE_CHAPTERS}",
    f"{NODE_ENHANCE_CHAPTERS} -. Send xN .-> {NODE_REVIEW_CHAPTERS}",
    f"{NODE_REVIEW_CHAPTERS} --> {NODE_DOCUMENT_CONSISTENCY_REVIEW}",
    f"{NODE_DOCUMENT_CONSISTENCY_REVIEW} --> {NODE_REPAIR_OR_ROUTE}",
    f"{NODE_REPAIR_OR_ROUTE} --> {NODE_MERGE_REVIEW}",
    f"{NODE_MERGE_REVIEW} --> {NODE_SYNC_LOCKED_TITLES}",
    f"{NODE_SYNC_LOCKED_TITLES} --> {NODE_PUBLISH}",
    f"{NODE_PUBLISH} --> {NODE_SYNC_KNOWLEDGE_GRAPH}",
    f"{NODE_SYNC_KNOWLEDGE_GRAPH} --> __end__",
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
        node_labels=DOCGEN_NODE_DISPLAY_NAMES,
        prompts=DOCGEN_PROMPTS,
    ),
    WorkflowGraphExport(
        key="digest_graph",
        title="Digest Knowledge-Doc Graph Sync",
        description="Knowledge-document based graph sync workflow. Parsed-file graph ingest has been removed.",
        build_graph=get_langgraph_dev_kg_doc_sync_graph,
        prompts=KG_PROMPTS,
    ),
)


__all__ = ["WORKFLOW_EXPORTS"]
