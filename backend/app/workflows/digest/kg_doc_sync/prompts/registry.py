"""Prompt registry used by workflow export tooling.

KG docs-sync has one LLM prompt family today: section graph extraction. The
graph/node code owns orchestration; prompt modules own the model contract.
"""

from app.workflows.digest.kg_doc_sync.prompts.section_graph import SECTION_GRAPH_PROMPTS

KG_PROMPTS = {
    **SECTION_GRAPH_PROMPTS,
}

__all__ = ["KG_PROMPTS"]
