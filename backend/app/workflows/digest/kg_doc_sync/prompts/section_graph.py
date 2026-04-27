"""Prompts for extracting graph candidates from one knowledge-doc section."""

from app.workflows.digest.kg_doc_sync.lib.ontology import (
    format_ontology_relation_type_bullets,
    format_ontology_unit_type_bullets,
)

_ALLOWED_NODE_TYPE_BULLETS = format_ontology_unit_type_bullets()
_ALLOWED_EDGE_TYPE_BULLETS = format_ontology_relation_type_bullets()

SYSTEM_PROMPT_KNOWLEDGE_EXTRACT = f"""
You extract a structured knowledge graph from one study-material chunk.

Return only nodes and edges that are directly supported by the chunk.

## Allowed node types
{_ALLOWED_NODE_TYPE_BULLETS}

## Allowed edge types
{_ALLOWED_EDGE_TYPE_BULLETS}

## Extraction rules
1. Prefer academically reusable knowledge units, not temporary wording.
2. Keep names short and canonical. Use LaTeX for math symbols when needed.
3. `local_summary` must summarize only what this chunk states.
4. Edge endpoints must exactly match returned node names.
5. Do not invent nodes or edges not grounded in the chunk.
6. Use Knowledge Unit granularity: one definition, one formula, one derivation step, one example, or one method step is a good unit.
7. Do not create nodes for whole chapters, whole sections, reading guides, or container headings unless the heading itself names one atomic concept.
8. Prefer 1-3 strong nodes over many weak nodes. Do not explode one section into many near-duplicate topic shells.
9. Reject pedagogical wrappers such as objectives, outlines, review slogans, task instructions, and question stems; extract only explicit reusable concepts or methods.

## Hierarchy rules
1. If the chunk heading names a real concept/topic, include that concept unless the chunk is purely procedural noise.
2. For `definition`, `formula`, `theorem`, `example`, `exercise`, `proof_step`, and `remark`, fill `parent_entity_name` when a parent concept/method is clear.
3. For `concept` and `method`, fill `taxonomy_hint` with the nearest broader concept when possible.

## Knowledge-doc specific rules
When the source is a structured knowledge document section:
1. Use the heading and body together.
2. Follow KU granularity strictly: chapter and section containers are usually not KUs; atomic definitions, formulas, proof steps, examples, and method steps usually are.
3. If the body contains an interpretation, property, formula, method, example, or note, extract it explicitly.
4. If labeled lines such as `定义:`, `公式:`, `例题:`, `Remark:` appear, convert them into typed nodes instead of leaving the section empty.
5. If the heading is generic like "几何意义", "性质", "方法", or "注意事项", combine it with the parent topic mentally and return the qualified atomic unit, not the generic heading alone.
6. It is acceptable to return an empty result when the section only contains objectives, outlines, review checklists, slogans, question stems, or procedural instructions.
7. Prefer a sparse high-quality graph over a non-empty graph padded with headings or task phrases.
""".strip()

USER_PROMPT_KNOWLEDGE_EXTRACT = """
## Chunk Metadata
- Title: {{ chunk_title }}
- Header path: {{ header_path }}
{% if doc_source_type %}- Source type: {{ doc_source_type }}{% endif %}
{% if subject_context %}- Subject context: {{ subject_context }}{% endif %}
{% if sibling_topics %}- Sibling topics: {{ sibling_topics }}{% endif %}
{% if digest_mode == "sprint" %}- Digest mode: sprint, prioritize methods, question types, and common mistakes.{% endif %}
{% if digest_mode == "systematic" %}- Digest mode: systematic, prioritize complete concepts, rigorous definitions, and prerequisite links.{% endif %}

{% if doc_source_type == "knowledge_doc_markdown" %}
## Special Instructions For This Chunk
- This chunk comes from a heading-scoped knowledge document.
- Use the heading and body together.
- If the body is explanatory rather than question-only, avoid returning an empty result.
- If the section describes a meaning, formula, property, method, example, or warning, extract those items explicitly.
- Favor KU-quality atomic units over broad section wrappers.
{% endif %}

## Chunk Content

{{ chunk_content }}
""".strip()

SECTION_GRAPH_PROMPTS = {
    "knowledge_extract_system": SYSTEM_PROMPT_KNOWLEDGE_EXTRACT,
    "knowledge_extract_user": USER_PROMPT_KNOWLEDGE_EXTRACT,
}

__all__ = [
    "SECTION_GRAPH_PROMPTS",
    "SYSTEM_PROMPT_KNOWLEDGE_EXTRACT",
    "USER_PROMPT_KNOWLEDGE_EXTRACT",
]
