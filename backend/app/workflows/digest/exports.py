"""Workflow graph exports for digest workflows."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.digest.graph import (
    build_curriculum_derive_graph,
    build_docgen_graph,
    build_kg_digest_graph,
)
from app.workflows.digest.planner.graph import get_langgraph_dev_planner_graph
from app.workflows.digest.prompts import KG_PROMPTS
from app.workflows.digest.unified.graph import build_unified_digest_graph

PLANNER_PROMPTS = {
    "planner_prompt": "构建方案规划提示词：负责输出全中文、可直接确认的章节方案。",
}

DOCGEN_PROMPTS = {
    "research_purify_prompt": "研究提纯提示词：负责把资料压缩为面向章节写作的中文研究笔记。",
    "writer_prompt": "章节写作提示词：负责按 sprint / systematic 契约生成教学化 Markdown。",
    "mermaid_prompt": "Mermaid 生成提示词：负责把章节知识关系转成中文 Mermaid mindmap。",
}


def _build_docgen_graph_for_export():
    """Wrap the docgen graph with a minimal export context."""

    ctx = WorkflowContext(
        workflow_name="digest.docgen",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=ctx)


def _build_unified_graph_for_export():
    """Wrap the unified graph with a minimal export context."""

    ctx = WorkflowContext(
        workflow_name="digest.unified",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_unified_digest_graph(context=ctx)


_DOCGEN_SEND_EDGES = (
    "load_context -. Send xN .-> targeted_research",
    "resolve_titles -. Send xN .-> pedagogy_craft",
    "pedagogy_craft --> collect_drafts",
    "collect_drafts --> enrich_document",
    "enrich_document --> inject_examine",
    "inject_examine --> finalize_assemble",
    "finalize_assemble --> __end__",
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
    WorkflowGraphExport(
        key="digest_curriculum",
        title="Digest Curriculum Workflow",
        description="Curriculum derivation workflow built from digest graph impact.",
        build_graph=build_curriculum_derive_graph,
    ),
    WorkflowGraphExport(
        key="digest_unified",
        title="Digest Unified Workflow",
        description="Shared prepare, docgen lane, graph lane, consistency, repair, and curriculum.",
        build_graph=_build_unified_graph_for_export,
    ),
)
