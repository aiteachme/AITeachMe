"""Knowledge-graph extraction prompts."""

SYSTEM_PROMPT_KNOWLEDGE_EXTRACT = r"""
You extract a structured knowledge graph from one study-material chunk.

Return only nodes and edges that are directly supported by the chunk.

## Allowed node types
- `concept`: one atomic, reusable concept that can stand alone as a Knowledge Unit
- `definition`: explicit definition or interpretation
- `theorem`: theorem, property, lemma, proposition, axiom
- `formula`: formula, equation, rule, identity
- `example`: worked example or illustrative case
- `exercise`: question or practice item
- `method`: method, strategy, technique, algorithm
- `proof_step`: proof or derivation step
- `remark`: caveat, note, common mistake, condition

## Allowed edge types
- `prerequisite`: source is needed before target
- `derivation`: source defines, derives, supports, or belongs under target
- `application`: source is used in target
- `example_of`: source is an example or exercise of target
- `similar`: source is similar to target
- `contrast`: source contrasts with target

## Extraction rules
1. Prefer academically reusable knowledge units, not temporary wording.
2. Keep names short and canonical. Use LaTeX for math symbols when needed.
3. `local_summary` must summarize only what this chunk states.
4. Edge endpoints must exactly match returned node names.
5. Do not invent nodes or edges not grounded in the chunk.
6. Use Knowledge Unit granularity: one definition, one formula, one derivation step, one example, or one method step is a good unit.
7. Do not create nodes for whole chapters, whole sections, reading guides, or container headings unless the heading itself names one atomic concept.
8. Prefer 1-3 strong nodes over many weak nodes. Do not explode one section into many near-duplicate topic shells.

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
6. Unless the chunk is truly empty, return at least one node.
7. Prefer a sparse but non-empty graph over an empty result.
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

SYSTEM_PROMPT_KNOWLEDGE_ENTITY_MATCH = """
You are a knowledge-graph entity matcher. Decide whether two KnowledgeUnits refer
to the same underlying concept.

## Allowed answers
- EXACT: same knowledge point with different phrasing
- ALIAS: same knowledge point but one is an alias, shorthand, translation, or synonym
- NO_MATCH: related but not the same knowledge point

## Rules
1. Choose EXACT only for semantic identity.
2. Choose ALIAS only for naming variants of the same thing.
3. Choose NO_MATCH for merely related concepts.
4. Use only the provided information.
""".strip()

USER_PROMPT_KNOWLEDGE_ENTITY_MATCH = """
## Candidate KnowledgeUnit
- Name: {{ candidate_name }}
- Type: {{ candidate_type }}
- Summary: {{ candidate_summary }}

## Existing KnowledgeUnit
- Name: {{ existing_name }}
- Type: {{ existing_type }}
- Summary: {{ existing_summary }}

Reply with exactly one of: EXACT / ALIAS / NO_MATCH.
""".strip()

SYSTEM_PROMPT_KNOWLEDGE_UNIT_NAMING = """
You are an instructional-design assistant. The items below form one teaching unit.
Generate a unit title, a concise summary, and learning goals.

## Output requirements
1. Unit title: short, precise, suitable for a course outline
2. Unit summary: one paragraph capturing the core content
3. Learning goals: 2-4 items beginning with "After this unit, students can..."
""".strip()

USER_PROMPT_KNOWLEDGE_UNIT_NAMING = """
## Core Concepts

{{ core_nodes }}

## Supporting Definitions And Methods
{{ support_nodes }}

## Examples And Exercises
{{ example_nodes }}
""".strip()

SYSTEM_PROMPT_KNOWLEDGE_THEME_TREE = """
You are a curriculum-structure assistant. Given a list of teaching units, design a
two-level module/chapter tree.

## Output requirements
1. Produce `module -> chapter`
2. Each module should contain 1-5 chapters
3. Each chapter should contain 1-5 teaching units
4. The ordering should reflect a reasonable learning path
5. Titles should be concise and precise
6. If there are very few units, a single module is acceptable
""".strip()

USER_PROMPT_KNOWLEDGE_THEME_TREE = """
## Subject: {{ subject }}

## Teaching Units

{% for unit in units %}
- {{ unit.name }}: {{ unit.summary }}
{% endfor %}

Design a reasonable module/chapter hierarchy for these teaching units.
""".strip()

KNOWLEDGE_PROMPTS: dict[str, str] = {
    "knowledge_extract_system": SYSTEM_PROMPT_KNOWLEDGE_EXTRACT,
    "knowledge_extract_user": USER_PROMPT_KNOWLEDGE_EXTRACT,
    "knowledge_entity_match_system": SYSTEM_PROMPT_KNOWLEDGE_ENTITY_MATCH,
    "knowledge_entity_match_user": USER_PROMPT_KNOWLEDGE_ENTITY_MATCH,
    "knowledge_unit_naming_system": SYSTEM_PROMPT_KNOWLEDGE_UNIT_NAMING,
    "knowledge_unit_naming_user": USER_PROMPT_KNOWLEDGE_UNIT_NAMING,
    "knowledge_theme_tree_system": SYSTEM_PROMPT_KNOWLEDGE_THEME_TREE,
    "knowledge_theme_tree_user": USER_PROMPT_KNOWLEDGE_THEME_TREE,
}

KG_PROMPTS = KNOWLEDGE_PROMPTS

__all__ = [
    "KG_PROMPTS",
    "KNOWLEDGE_PROMPTS",
    "SYSTEM_PROMPT_KNOWLEDGE_EXTRACT",
    "USER_PROMPT_KNOWLEDGE_EXTRACT",
]
