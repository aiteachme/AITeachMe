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
)

_QUESTION_TYPE_FORMAT_RULES = (
    "\nQuestion type formatting rules:\n"
    "- single_choice: provide exactly 4 distinct options; correct_answer must exactly equal one option.\n"
    "- fill_blank: do not provide options; correct_answer must be short and unique.\n"
    "- Only return question_type values that appear in question_specs; do not invent unsupported types.\n"
)

SYSTEM_PROMPT_EXAM_QUESTION_BUILD = """
你是一名严格、资深、重视教学效果的命题老师。

你的任务是基于给定的知识点清单生成高质量试题。题目必须：
- 紧扣指定知识点，不得脱离材料范围自由发散
- 难度真实，不出无意义的“定义背诵题”或纯凑数题
- 题干表达准确、自然、无歧义
- 选项题必须只有一个最佳答案，干扰项要“看起来合理但本质错误”
- 填空题答案必须简洁唯一，不得依赖模糊表述
- 解析要简洁但有教学价值，指出为什么对、为什么错、考点是什么

输出必须完全遵守结构化 schema，不要输出任何额外说明。
""".strip()


def build_exam_question_messages(
    *,
    subject: str,
    exam_mode: str,
    focus_prompt: str,
    user_prompt: str,
    style_prompt: str,
    requested_question_count: int,
    units: list[dict[str, Any]],
    specs: list[dict[str, Any]],
) -> list[ChatMessage]:
    payload = {
        "subject": subject,
        "exam_mode": exam_mode,
        "requested_question_count": requested_question_count,
        "focus_prompt": focus_prompt or "",
        "user_prompt": user_prompt or "",
        "style_prompt": style_prompt or "",
        "knowledge_units": units,
        "question_specs": specs,
    }
    user_prompt_text = (
        "请按给定知识点与题目规格生成一组高质量试题。\n"
        "要求：\n"
        "1. 每个题目必须主要对应一个 knowledge_unit_id。\n"
        "2. question_type 和 difficulty 必须严格匹配给定规格。\n"
        "3. single_choice 必须提供 4 个不同选项，且 correct_answer 必须精确等于其中一个选项。\n"
        "4. fill_blank 不要提供 options，答案要简短唯一。\n"
        "5. 当前只允许生成 single_choice 和 fill_blank，不要返回 true_false、short_answer、multiple_choice 或其他题型。\n"
        "6. 题干不要直接泄露答案；解析不要空泛。\n"
        "7. 优先考查理解、辨析、应用、迁移，不要只考死记硬背。\n\n"
        "输入数据如下：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text + "\n\n如出现数学公式，必须使用 LaTeX，并用 `$...$` 或 `$$...$$` 包裹。"},
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
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_EXAM_QUESTION_BUILD + _QUESTION_TYPE_FORMAT_RULES + _LATEX_FORMAT_RULES},
        {"role": USER, "content": user_prompt_text + "\n\n如出现数学公式，必须使用 LaTeX，并用 `$...$` 或 `$$...$$` 包裹。"},
    ]
