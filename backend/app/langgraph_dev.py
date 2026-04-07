"""LangGraph dev entrypoints for local workflow debugging.

These graphs are additive debug surfaces for LangGraph Studio / ``langgraph dev``.
They intentionally do not replace existing FastAPI or service-layer entrypoints.
"""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.digest.curriculum.graph import build_curriculum_derive_graph
from app.workflows.digest.docs.graph import build_docgen_graph
from app.workflows.digest.kg.graph import build_kg_digest_graph
from app.workflows.digest.unified.graph import build_unified_digest_graph
from app.workflows.examine.exam_grade_workflow import build_exam_grade_graph
from app.workflows.examine.question_build_workflow import build_question_build_graph
from app.workflows.ingest.graph import build_deep_enhance_graph, build_parse_file_graph
from app.workflows.interact.graph import build_interact_workflow_graph
from app.workflows.profile.graph import build_profile_pipeline_graph


def _build_context(workflow_name: str) -> WorkflowContext:
    return WorkflowContext(
        workflow_name=workflow_name,
        subject="__langgraph_dev__",
        event_bus=InProcessEventBus(),
    )


ingest_fast_parse_graph = build_parse_file_graph(
    context=_build_context("ingest.file.parse.langgraph_dev"),
).compile()

ingest_deep_enhance_graph = build_deep_enhance_graph().compile()

digest_kg_graph = build_kg_digest_graph().compile()

digest_curriculum_graph = build_curriculum_derive_graph().compile()

digest_docgen_graph = build_docgen_graph(
    context=_build_context("digest.docgen.langgraph_dev"),
).compile()

digest_unified_graph = build_unified_digest_graph(
    context=_build_context("digest.unified.langgraph_dev"),
).compile()

interact_chat_graph = build_interact_workflow_graph(
    context=_build_context("interact.chat.langgraph_dev"),
).compile()

examine_question_build_graph = build_question_build_graph().compile()

examine_exam_grade_graph = build_exam_grade_graph().compile()

profile_pipeline_graph = build_profile_pipeline_graph().compile()


__all__ = [
    "digest_curriculum_graph",
    "digest_docgen_graph",
    "digest_kg_graph",
    "digest_unified_graph",
    "examine_exam_grade_graph",
    "examine_question_build_graph",
    "ingest_deep_enhance_graph",
    "ingest_fast_parse_graph",
    "interact_chat_graph",
    "profile_pipeline_graph",
]
