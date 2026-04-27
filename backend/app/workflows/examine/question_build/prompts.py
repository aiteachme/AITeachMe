"""Prompt builders for LLM-based exam question generation."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.llm import ChatMessage, SYSTEM, USER

_LATEX_FORMAT_RULES = (
    "\nMath formatting rules:\n"
    "- If the stem, correct_answer, or explanation contains mathematical formulas, use valid LaTeX only.\n"
    "- Inline math must use `$...$`; display math must use `$$...$$`.\n"
    "- Do not output bare TeX commands without `$` delimiters.\n"
    "- Do not use `\\(...\\)` or `\\[...\\]`.\n"
    "- Never put `{{blank}}` inside `$...$` or `$$...$$` math.\n"
    "- Do not create LaTeX blanks such as `\\text{___}`. Put `{{blank}}` in the surrounding body text instead.\n"
)

_QUESTION_TYPE_FORMAT_RULES = (
    "\nQuestion type formatting rules:\n"
    "- The stem must contain only the problem statement; never duplicate or embed options inside stem.\n"
    "- Use one canonical choice format only: options must be a JSON array of strings, never an object/map.\n"
    "- Choice options must be exactly 4 plain option texts in order; never prefix options with A/B/C/D labels.\n"
    "- single_choice: provide exactly 4 distinct options and correct_indices with exactly one zero-based index, for example `[0]`.\n"
    "- multiple_choice: provide exactly 4 distinct options and correct zero-based indices, for example `[0]` or `[0, 2]`.\n"
    "- For single_choice and multiple_choice, do not provide correct_answer; the backend derives A/B/C/D labels from correct_indices.\n"
    "- true_false: do not provide options; correct_answer must be True or False.\n"
    "- fill_blank: do not provide options; put the blank in the stem as `{{blank}}`; correct_answer must be short and unique.\n"
    "- short_answer: do not provide options; correct_answer should be concise but complete.\n"
    "- Only return question_type values that appear in the provided question spec; do not invent unsupported types.\n"
)

SYSTEM_PROMPT_EXAM_QUESTION_BUILD = """
You are AITeachMe's careful exam-question writer. Generate high-quality exam
questions from the provided subject context, user intent, knowledge units, and
question specification. Each question must stay tightly grounded in the assigned
knowledge units and must not invent facts outside the supplied material. Prefer
questions that test understanding, analysis, application, and transfer instead
of shallow definition recall. Return only data that matches the requested
structured schema; do not include commentary or extra text.
""".strip()


def _subject_payload(
    *,
    subject: str,
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
) -> dict[str, str]:
    return {
        "subject_id": subject,
        "subject_name": subject_name or subject,
        "subject_description": subject_description or "",
        "user_intent": subject_user_intent or "",
    }


def build_exam_knowledge_unit_filter_messages(
    *,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    exam_mode: str,
    requested_question_count: int,
    candidate_limit: int,
    user_prompt: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    priority_unit_ids: list[int] | None = None,
    weak_unit_ids: list[int] | None = None,
    system_constraints: str = "",
) -> list[ChatMessage]:
    payload = {
        "subject_profile": {
            "subject_name": subject_name or "",
            "subject_description": subject_description or "",
            "user_intent": subject_user_intent or "",
        },
        "exam_mode": exam_mode,
        "requested_question_count": requested_question_count,
        "candidate_limit": candidate_limit,
        "user_prompt": user_prompt or "",
        "system_constraints": system_constraints or "",
        "priority_knowledge_unit_ids": list(priority_unit_ids or []),
        "weak_knowledge_unit_ids": list(weak_unit_ids or []),
        "knowledge_graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }
    prompt = f"""
Select candidate knowledge units for the later exam-blueprint planning step.
Do not generate questions and do not assign question types in this step.

Graph input notes:
- knowledge_graph.nodes contains the available knowledge-unit IDs and names.
- knowledge_graph.edges contains source_id and target_id values that show graph
  relationships between knowledge units.
- Do not assume any knowledge units outside knowledge_graph.nodes.

Interpret the scope implied by user_prompt:
- If the user asks to only test a limited scope, set scope_strict to true and
  choose only units inside that scope.
- If the user asks to focus on, review, or emphasize a topic, prioritize related
  units but include necessary foundations or connected units when useful.
- If the user excludes a topic, do not choose matching knowledge units.
- If no clear scope is provided, choose units that best fit the subject goals,
  exam_mode, priority_knowledge_unit_ids, and weak_knowledge_unit_ids.

Selection rules:
- knowledge_unit_ids must come only from knowledge_graph.nodes. Never invent IDs.
- Output order is recommendation priority; earlier IDs are more important.
- Return at most candidate_limit IDs. Return fewer if strict scope has fewer units.
- Coverage should fit requested_question_count and avoid near-duplicate units.
- For paper_exam, prefer weak points and broad coverage. For web_practice,
  prefer review and practice value.
- Keep rationale brief for debugging and auditability.

Return valid JSON only, shaped like:
{{
  "knowledge_unit_ids": [1, 2, 3],
  "scope_include_terms": ["..."],
  "scope_exclude_terms": ["..."],
  "scope_strict": false,
  "rationale": "..."
}}

Input: {json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": "You select exam knowledge-unit candidates. Return valid JSON only."},
        {"role": USER, "content": prompt},
    ]


def build_exam_question_blueprint_messages(
    *,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    exam_mode: str,
    requested_question_count: int,
    user_prompt: str,
    units: list[dict[str, Any]],
    question_prompt_plans: list[dict[str, Any]] | None = None,
    system_constraints: str = "",
) -> list[ChatMessage]:
    payload = {
        "subject_profile": {
            "subject_name": subject_name or "",
            "subject_description": subject_description or "",
            "user_intent": subject_user_intent or "",
        },
        "exam_mode": exam_mode,
        "requested_question_count": requested_question_count,
        "user_prompt": user_prompt or "",
        "system_constraints": system_constraints or "",
        "knowledge_units": units,
        "question_prompt_plans": list(question_prompt_plans or []),
    }
    prompt = f"""
Plan the knowledge-unit blueprint for this exam. Do not generate concrete questions.

For each question decide:
1. item_order: consecutive numbers from 1 to requested_question_count.
2. question_type: copy exactly from question_prompt_plans for the same item_order.
3. difficulty: easy / medium / hard, chosen after considering question_type and knowledge_units.
4. knowledge_unit_ids: choose IDs from knowledge_units. Do not invent IDs. Prefer 1 unit for true_false/fill_blank, 1-2 for choice questions, and 1-3 for short_answer when the concepts naturally connect.
5. rationale: brief reason for the unit/type/difficulty combination.

The output count must exactly equal requested_question_count.
Return valid JSON only, shaped like:
{{
  "blueprints": [
    {{
      "item_order": 1,
      "knowledge_unit_ids": [1, 2],
      "question_type": "single_choice",
      "difficulty": "medium",
      "rationale": "..."
    }}
  ]
}}

Input: {json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": "You are an exam blueprint planner. Return valid JSON only."},
        {"role": USER, "content": prompt},
    ]


def build_exam_question_requirement_messages(
    *,
    exam_mode: str,
    requested_question_count: int,
    user_prompt: str,
) -> list[ChatMessage]:
    payload = {
        "exam_mode": exam_mode,
        "requested_question_count": requested_question_count,
        "user_prompt": user_prompt or "",
    }
    prompt = f"""
请把用户的考卷生成要求拆解为每道题的题型和生成要求。

规则：
- 必须为 1 到 requested_question_count 的每个 item_order 输出且只输出一条记录。
- 每道题必须选择一个 question_type，可选值只能是：single_choice / multiple_choice / true_false / fill_blank / short_answer。
- user_prompt 中的全局风格、整体范围、表达形式等要求，必须写入每一道匹配题目的 generation_prompt。
- 如果 user_prompt 中包含针对特定题号、题号范围、题目分组或题型的要求，只能把这些要求写入对应题目的 generation_prompt。
- 这个阶段不要分配 knowledge_unit_ids，也不要输出 difficulty 字段；后续节点会在看到题型后再分配知识单元和难度。
- 这个阶段不要引入学科画像、知识单元详情、多样性运行 ID 或系统约束。
- 每个 generation_prompt 要简洁，聚焦于用户对该题的生成要求。
- 如果用户没有为某道题提出任何可写入该题 generation_prompt 的要求，就把该题 generation_prompt 写为“无”，不要自行补充中性要求。

只能返回合法 JSON，结构如下：
{{
  "prompts": [
    {{"item_order": 1, "question_type": "single_choice", "generation_prompt": "..."}}
  ]
}}

输入：{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": "你是考卷生成中的题型和单题要求规划器。只能返回合法 JSON。"},
        {"role": USER, "content": prompt},
    ]


def build_exam_question_messages(
    *,
    units: list[dict[str, Any]],
    spec: dict[str, Any],
    generation_prompt: str,
    subject_profile: dict[str, str] | None = None,
    system_constraints: str = "",
) -> list[ChatMessage]:
    payload = {
        "subject_profile": subject_profile or {},
        "system_constraints": system_constraints or "",
        "generation_prompt": generation_prompt or "",
        "knowledge_units": units,
        "question_spec": spec,
    }
    user_prompt_text = f"""
Generate one high-quality exam question from the provided knowledge units and
question specification.

Requirements:
0. generation_prompt is the complete generation instruction for this item.
   Follow it strictly. Do not look outside this payload for additional global
   user requirements or subject requirements.
1. The generated question must match question_spec.item_order,
   question_spec.question_type, and question_spec.difficulty.
2. question_spec.allocation_rationale explains why these knowledge units were
   assigned to this item. Use it as planning context for the tested angle and
   coverage, but do not quote or expose it in the stem, options, answer, or
   explanation.
3. Use knowledge_unit_refs to describe the knowledge units covered by this
   question. Do not output a separate knowledge_unit_id field.
   knowledge_unit_refs[*].knowledge_unit_id must be a real knowledge_unit_id
   from knowledge_units and must also appear in question_spec.knowledge_unit_ids.
4. Every object in knowledge_units contains a real knowledge_unit_id. Do not
   treat labels such as "knowledge unit 1" or "knowledge unit 2" as IDs. If
   generation_prompt references positional unit numbers, map them to real IDs
   using the order in question_spec.knowledge_unit_ids.
5. Each knowledge_unit_refs item must include coverage_weight.
   coverage_weight is this question's coverage share for that unit; weights
   should sum to about 1.0. Higher coverage_weight means the unit is more
   central to the question; do not output a separate role field.
   knowledge_unit_refs must be a JSON array of objects, never strings. Correct:
    `"knowledge_unit_refs": [{{"knowledge_unit_id": 46, "coverage_weight": 1.0}}]`.
    Incorrect: `"knowledge_unit_refs": ["primary", "secondary"]`.
    Incorrect: `"knowledge_unit_refs": ["knowledge_unit_id: 46, coverage_weight: 1.0"]`.
6. If question_spec.knowledge_unit_ids contains multiple IDs, cover the related
   concepts naturally. If the question only materially tests one concept, return
   a single ref with coverage_weight=1.0.
7. The stem, options, and explanation must not expose internal references such
   as "knowledge unit 1", "knowledge unit 2", or database IDs. Use knowledge
   point names when the tested concept needs to be mentioned.
8. Do not reveal the answer directly in the stem. The explanation should cover
   the tested point, the correct reasoning, and common mistakes.
9. For fill_blank stems, use `{{{{blank}}}}` in normal text only. Do not place
   `{{{{blank}}}}` inside LaTeX math.
Choice output contract:
- For single_choice and multiple_choice, `options` must be pure option text only, for example `["option one", "option two", "option three", "option four"]`.
- For single_choice and multiple_choice, use `correct_indices` only, with zero-based indices, for example `[0]` or `[0, 2]`.
- Do not put A/B/C/D labels inside options, and do not return `correct_answer` for choice questions.

Input: {json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text},
    ]


def build_text_exam_messages(
    *,
    subject: str,
    knowledge_text: str,
    num_questions: int,
    difficulty: str,
) -> list[ChatMessage]:
    payload = {
        "subject": subject,
        "num_questions": num_questions,
        "difficulty": difficulty,
        "knowledge_text": knowledge_text[:12000],
    }
    user_prompt_text = (
        "Generate a set of high-quality exam questions directly from the given learning material.\n"
        "Cover core concepts, methods, and common mistakes. Avoid duplicate questions and return structured output.\n\n"
        "For fill_blank stems, use `{{blank}}` for the blank and keep it outside any LaTeX math delimiters.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text},
    ]
