"""Compatibility prompt exports for digest workflows.

Prefer lane-local imports from:

- `app.workflows.digest.planner.prompts`
- `app.workflows.digest.docgen.prompts`
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "KG_PROMPTS",
    "PROMPTS",
    "SYSTEM_PROMPT_KG_ENTITY_MATCH",
    "SYSTEM_PROMPT_KG_EXTRACT",
    "SYSTEM_PROMPT_KG_THEME_TREE",
    "SYSTEM_PROMPT_KG_UNIT_NAMING",
    "USER_PROMPT_KG_ENTITY_MATCH",
    "USER_PROMPT_KG_EXTRACT",
    "USER_PROMPT_KG_THEME_TREE",
    "USER_PROMPT_KG_UNIT_NAMING",
    "build_docgen_gap_query_messages",
    "build_docgen_heading_repair_messages",
    "build_docgen_mermaid_prompt",
    "build_docgen_research_purify_messages",
    "build_docgen_sub_query_messages",
    "build_docgen_writer_messages",
    "build_planner_chapter_title_messages",
    "build_planner_prompt",
]

_ATTR_TO_MODULE = {
    "PROMPTS": "app.workflows.digest.prompts.prompts",
    "KG_PROMPTS": "app.workflows.digest.prompts.kg_prompts",
    "SYSTEM_PROMPT_KG_EXTRACT": "app.workflows.digest.prompts.kg_prompts",
    "USER_PROMPT_KG_EXTRACT": "app.workflows.digest.prompts.kg_prompts",
    "SYSTEM_PROMPT_KG_ENTITY_MATCH": "app.workflows.digest.prompts.kg_prompts",
    "USER_PROMPT_KG_ENTITY_MATCH": "app.workflows.digest.prompts.kg_prompts",
    "SYSTEM_PROMPT_KG_UNIT_NAMING": "app.workflows.digest.prompts.kg_prompts",
    "USER_PROMPT_KG_UNIT_NAMING": "app.workflows.digest.prompts.kg_prompts",
    "SYSTEM_PROMPT_KG_THEME_TREE": "app.workflows.digest.prompts.kg_prompts",
    "USER_PROMPT_KG_THEME_TREE": "app.workflows.digest.prompts.kg_prompts",
    "build_planner_chapter_title_messages": "app.workflows.digest.planner.prompts",
    "build_planner_prompt": "app.workflows.digest.planner.prompts",
    "build_docgen_gap_query_messages": "app.workflows.digest.docgen.prompts",
    "build_docgen_heading_repair_messages": "app.workflows.digest.docgen.prompts",
    "build_docgen_mermaid_prompt": "app.workflows.digest.docgen.prompts",
    "build_docgen_research_purify_messages": "app.workflows.digest.docgen.prompts",
    "build_docgen_sub_query_messages": "app.workflows.digest.docgen.prompts",
    "build_docgen_writer_messages": "app.workflows.digest.docgen.prompts",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
