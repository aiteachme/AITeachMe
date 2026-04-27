"""Prompt registry used by workflow export tooling."""

from app.workflows.digest.kg_doc_sync.prompts.section_graph import SECTION_GRAPH_PROMPTS

KG_PROMPTS = {
    **SECTION_GRAPH_PROMPTS,
}

__all__ = ["KG_PROMPTS"]
