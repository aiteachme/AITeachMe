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
    "- Use one canonical choice format only: options must be a JSON array of strings, never an object/map.\n"
    "- Choice options must be exactly 4 plain option texts in order; never prefix options with A/B/C/D labels.\n"
    "- single_choice: provide exactly 4 distinct options and correct_indices with exactly one zero-based index, for example `[0]`.\n"
    "- multiple_choice: provide exactly 4 distinct options and correct_indices with all correct zero-based indices, for example `[0, 2]`.\n"
    "- For single_choice and multiple_choice, do not provide correct_answer; the backend derives A/B/C/D labels from correct_indices.\n"
    "- true_false: do not provide options; correct_answer must be True or False.\n"
    "- fill_blank: do not provide options; put the blank in the stem as `{{blank}}`; correct_answer must be short and unique.\n"
    "- short_answer: do not provide options; correct_answer should be concise but complete.\n"
    "- Only return question_type values that appear in the provided question spec; do not invent unsupported types.\n"
)

SYSTEM_PROMPT_EXAM_QUESTION_BUILD = """
你是 AITeachMe 的严谨命题老师。
你的任务是基于给定学科上下文、用户意图、知识单元与题目规格生成高质量试题。
题目必须紧扣指定知识单元，不得脱离材料范围自由发散。
题目要考查理解、辨析、应用、迁移，避免无意义的定义背诵。
输出必须完全遵守结构化 schema，不要输出任何额外说明。
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


def build_exam_question_blueprint_messages(
    *,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    exam_mode: str,
    requested_question_count: int,
    user_prompt: str,
    units: list[dict[str, Any]],
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
    }
    prompt = f"""
请先编排试题蓝图，不要生成具体题目。

你需要决定每道题：
1. item_order：从 1 到 requested_question_count 连续编号；
2. question_type：single_choice / multiple_choice / true_false / fill_blank / short_answer；
3. difficulty：easy / medium / hard；
4. knowledge_unit_ids：本题要测试的知识单元，建议 1-3 个；可以多个，但必须能自然放进同一道题；
5. rationale：为什么这些知识单元和题型适合放在一起。

编排原则：
- 必须从给定 knowledge_units 中选择，不要 invent 新 id。
- 优先结合 mastery_score、用户意图、user_prompt 来安排重点。
- 必须为每道题生成 generation_prompt。它是单题生成阶段唯一承接整体要求与本题特殊要求的字段。
- generation_prompt 要综合 user_prompt（最高优先级）、subject_description、user_intent、exam_mode、system_constraints，并具体说明本题的风格、设计方式、情境、能力层级、避免事项和与整卷的配合。
- 如果用户对某个题号、某类题、整体风格或难度有要求，要在对应题目的 generation_prompt 中明确落地。
- 多知识单元题要选择概念相关、方法连续、易混淆或能共同组成应用场景的单元。
- 不要每题都只覆盖一个知识单元；但也不要把无关单元硬塞在一起。
- 输出数量必须等于 requested_question_count。

只输出合法 JSON，形如：
{{
  "blueprints": [
    {{
      "item_order": 1,
      "knowledge_unit_ids": [1, 2],
      "question_type": "single_choice",
      "difficulty": "medium",
      "rationale": "...",
      "generation_prompt": "..."
    }}
  ]
}}

输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": "你是考试题目蓝图编排器，只输出合法 JSON。"},
        {"role": USER, "content": prompt},
    ]


def build_exam_question_messages(
    *,
    units: list[dict[str, Any]],
    spec: dict[str, Any],
    generation_prompt: str,
) -> list[ChatMessage]:
    payload = {
        "generation_prompt": generation_prompt or "",
        "knowledge_units": units,
        "question_spec": spec,
    }
    user_prompt_text = f"""
请按给定知识单元与题目规格生成高质量试题。

要求：
0. generation_prompt 是本题的完整生成要求，必须严格遵守；不要再向外部寻找全局用户要求或学科要求。
1. 每道题必须匹配对应 item_order、question_type 和 difficulty。
2. 使用 knowledge_unit_refs 表达本题覆盖的知识单元，不要输出单独的 knowledge_unit_id 字段；knowledge_unit_refs 中的 knowledge_unit_id 必须来自 question_spec.knowledge_unit_ids。
3. 如果 question_spec.knowledge_unit_ids 有多个，本题要自然覆盖这些相关知识点。
4. knowledge_units 按 question_spec.knowledge_unit_ids 的顺序排列；不要要求 knowledge_units 自身包含 id。
5. 不要直接泄露答案；解析要说明考点、正确原因和常见误区。
6. fill_blank stems 使用 `{{{{blank}}}}`，并且 `{{{{blank}}}}` 只能在正文中，不能放进 LaTeX 公式。

Choice output contract:
- For single_choice and multiple_choice, `options` must be pure option text only, for example `["option one", "option two", "option three", "option four"]`.
- For single_choice and multiple_choice, use `correct_indices` only, with zero-based indices, for example `[0]` or `[0, 2]`.
- Do not put A/B/C/D labels inside options, and do not return `correct_answer` for choice questions.

输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text},
    ]


def build_question_weight_messages(
    *,
    subject: str,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    question: dict[str, Any],
    units: list[dict[str, Any]],
) -> list[ChatMessage]:
    payload = {
        "subject": _subject_payload(
            subject=subject,
            subject_name=subject_name,
            subject_description=subject_description,
            subject_user_intent=subject_user_intent,
        ),
        "question": question,
        "candidate_knowledge_units": units,
    }
    prompt = f"""
请根据题目内容，为该题涉及的候选知识单元分配 coverage_weight。

要求：
- 只能使用 candidate_knowledge_units 中的 knowledge_unit_id。
- 权重总和应约等于 1.0。
- 最主要知识单元 role 为 primary，其余为 secondary。
- 如果题目实质只考一个知识单元，就只返回一个权重 1.0 的 primary。

只输出合法 JSON：
{{
  "item_order": 1,
  "knowledge_unit_refs": [
    {{"knowledge_unit_id": 1, "coverage_weight": 0.7, "role": "primary"}},
    {{"knowledge_unit_id": 2, "coverage_weight": 0.3, "role": "secondary"}}
  ]
}}

输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": SYSTEM, "content": "你是试题知识点覆盖权重分析器，只输出合法 JSON。"},
        {"role": USER, "content": prompt},
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
        "请基于给定学习材料直接命制一组高质量试题。\n"
        "题目要覆盖核心概念、方法和易错点，避免重复，输出结构化结果。\n\n"
        "For fill_blank stems, use `{{blank}}` for the blank and keep it outside any LaTeX math delimiters.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text},
    ]
