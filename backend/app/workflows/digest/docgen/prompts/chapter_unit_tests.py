"""Prompts for chapter-end unit test generation."""

from __future__ import annotations

import json

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_chapter_unit_test_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    required_elements: list[str],
    chapter_end_practice_plan: list[dict[str, object]],
    markdown: str,
    min_items: int,
    max_items: int,
) -> list[dict[str, str]]:
    """Build a compact prompt for structured chapter-end unit tests."""

    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    required_text = "、".join(item for item in required_elements if item) or "本章核心概念、方法和易错点"
    system_prompt = """
你是 AITeachMe 的章末测验设计器。
只设计本章末尾的短测题；题目贴合本章正文和执行计划。
选择类题目提供四个短选项；填空题和短答题直接作答，不伪装成选择题。
每题都有答案、判定依据或解析要点，并覆盖不同认知动作。
解析要写成可分行展示的短步骤，不要把完整解题过程挤成一长句。
输出前必须逐题独立作答并复算，不能先假定自己拟定的答案正确。
""".strip()
    user_prompt = f"""
请为这一章生成结构化章末单元测试。

章节标题：{chapter_title}
文档模式：{mode_label}
题量范围：{min_items}-{max_items}
必须覆盖：{required_text}
章末测试计划：{chapter_end_practice_plan}

输出 JSON 字段：
- chapter_index: 整数，无法判断时填 1
- items: 数组，每项包含 type、difficulty、target、stem、options、answer、basis

type 表示这道题考查的能力类型，只能从以下类型中选择，尽量不要重复：
- 概念判断：判断概念、条件、边界是否成立
- 选择题：直接选择最合适的一项
- 填空题：补全公式、关键步骤、结论或条件
- 步骤排序：排列方法步骤、流程、推导链
- 错因辨析：识别错误说法、易混点、反例或限制
- 短答题：用短句解释原因、机制或核心结论
- 应用迁移：换一个情境做小变式或案例判断
- 图表读取：读取图、表、代码、结构图、流程图里的关键信息
- 推导证明：给出关键推导入口、证明链或依据

difficulty 只能填：基础、进阶、挑战。

题目要求：
1. 题量必须落在“题量范围”内；紧凑模式优先少而准，正文或用户需求较密时才接近题量上限。
2. 题量为 4-5 题至少覆盖 4 类题型；6-8 题至少覆盖 5 类题型；9 题以上至少覆盖 6 类题型，且同一 target 不要连续重复。
3. 每题围绕一个具体知识点、方法步骤、易错边界、图表读取、案例判断或迁移任务，不要泛泛问“谈谈理解”。
4. target 写成具体考点名，用于展示“考点覆盖”；不要写“任务 1”“本章要点”这类空标签。
5. stem、answer、basis 都要短，公式使用 Markdown/LaTeX，例如 `$f(x)$` 或 `$$...$$`；不要输出裸 `\\sqrt`、`\\frac`，也不要输出 HTML。
6. 只有选择题的 options 必须正好 4 项，stem 中不要写 A/B/C/D；answer 写正确选项的完整文本，不要只写 A/B/C/D 字母。
7. 判断、填空、短答、步骤排序、错因辨析、应用迁移、图表读取和推导证明的 options 必须是空数组 `[]`，直接在 stem 中给出可作答任务，并在 answer 中写明确结论或步骤。
8. 题目只围绕本章正文里的知识点、方法和易错边界；正文已有练习时，改成同知识点的小变式。
9. basis 写 2-4 个短步骤，优先用 `1. ... 2. ...` 或用分号分隔；每一步说明一个判断依据、计算动作或错因边界。
10. 输出前逐题校验：题干条件足够且答案唯一；选择题的正确答案必须确实是四个选项之一，另外三项不等价、不重复且确实错误；basis 的每一步推导都成立，最终结论必须与 answer 完全一致。极限、定义域、正负号、单位、边界条件和充分/必要条件要重点复算。
11. 只输出 JSON 对象；答案是否默认折叠由渲染层负责，你只保证 answer 与 basis 完整、可分行。

本章正文：
{markdown}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_chapter_unit_tests",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "required_count": len(required_elements),
            "plan_count": len(chapter_end_practice_plan),
            "markdown_chars": len(markdown),
            "min_items": min_items,
            "max_items": max_items,
        },
        output=messages,
    )


def build_chapter_unit_test_review_messages(
    *,
    chapter_title: str,
    digest_mode: str,
    required_elements: list[str],
    chapter_end_practice_plan: list[dict[str, object]],
    markdown: str,
    candidate: dict[str, object] | None,
    generation_issue: str,
    min_items: int,
    max_items: int,
) -> list[dict[str, str]]:
    """Build the independent answer/solution review prompt for one chapter test."""

    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    required_text = "、".join(item for item in required_elements if item) or "本章核心概念、方法和易错点"
    candidate_text = json.dumps(candidate or {}, ensure_ascii=False, indent=2)
    system_prompt = """
你是 AITeachMe 的章末测验复核老师。你必须独立解答每道题，不能默认候选答案和解析正确。
请根据本章正文逐题复算条件、结论、选项和解析；发现错误、歧义、缺项或结构问题时直接修正。
最终返回一份完整可发布的题组，而不是评语、差异或局部补丁。
""".strip()
    user_prompt = f"""
请复核并重写下面的章末单元测试，返回完整 JSON 对象。

章节标题：{chapter_title}
文档模式：{mode_label}
题量范围：{min_items}-{max_items}
必须覆盖：{required_text}
章末测试计划：{chapter_end_practice_plan}
初稿生成或结构问题：{generation_issue or "无"}

输出 JSON 字段：
- chapter_index: 整数，无法判断时填 1
- items: 数组，每项包含 type、difficulty、target、stem、options、answer、basis

复核要求：
1. 题量必须在范围内；初稿缺失或不可用时，依据正文重新生成完整题组。
2. 每题题干条件必须充分，答案必须唯一或明确列出全部正确结论。
3. 选择题必须正好有 4 个互不重复的选项，answer 写正确选项全文；其余题型 options 必须为 `[]`。
4. 必须独立复算数学运算、公式、定义域、正负号、单位、边界条件以及充分必要条件。
5. basis 写 2-4 个成立的短步骤，最终结论必须与 answer 一致，不能沿用初稿中的错误推理。
6. 题目只使用正文能够支持的知识，不编造正文之外的定理、数据或条件。
7. type 只能从概念判断、选择题、填空题、步骤排序、错因辨析、短答题、应用迁移、图表读取、推导证明中选择；difficulty 只能填基础、进阶、挑战。
8. 公式使用 Markdown/LaTeX；只输出 JSON，不输出复核说明或 Markdown 代码块。

候选题组：
{candidate_text}

本章正文：
{markdown}
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trace_prompt_build(
        "docgen_chapter_unit_test_review",
        inputs={
            "chapter_title": chapter_title,
            "digest_mode": digest_mode,
            "required_count": len(required_elements),
            "plan_count": len(chapter_end_practice_plan),
            "markdown_chars": len(markdown),
            "candidate_item_count": len(list((candidate or {}).get("items") or [])),
            "generation_issue": generation_issue,
            "min_items": min_items,
            "max_items": max_items,
        },
        output=messages,
    )


__all__ = [
    "build_chapter_unit_test_messages",
    "build_chapter_unit_test_review_messages",
]
