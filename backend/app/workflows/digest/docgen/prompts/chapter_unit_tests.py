"""Prompts for chapter-end unit test generation."""

from __future__ import annotations

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
每题都有答案、判定依据或解析要点，并覆盖不同认知动作。
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
- items: 数组，每项包含 type、difficulty、target、stem、answer、basis

type 只能从以下题型中选择，尽量不要重复：
- 概念判断：判断概念、条件、边界是否成立
- 选择题：给出 3-4 个短选项，让学生选最合适的一项
- 填空题：补全公式、关键步骤、结论或条件
- 步骤排序：排列方法步骤、流程、推导链
- 错因辨析：识别错误说法、易混点、反例或限制
- 短答题：用短句解释原因、机制或核心结论
- 应用迁移：换一个情境做小变式或案例判断
- 图表读取：读取图、表、代码、结构图、流程图里的关键信息
- 推导证明：给出关键推导入口、证明链或依据

difficulty 只能填：基础、进阶、挑战。

题目要求：
1. 题量为 1 题时使用最贴切题型；2-3 题尽量每题不同；4-5 题至少覆盖 4 类题型；6 题以上至少覆盖 5 类题型。
2. 每题围绕一个具体知识点、方法步骤、易错边界、图表读取、案例判断或迁移任务，不要泛泛问“谈谈理解”。
3. stem、answer、basis 都要短，适合渲染成卡片式单元检测；答案会默认折叠，点击后展开。
4. 选择题必须把选项写在 stem 中；填空题必须有明确空位；步骤排序必须给出待排序步骤。
5. 题目只围绕本章正文里的知识点、方法和易错边界；正文已有练习时，改成同知识点的小变式。
6. 只输出 JSON 对象。

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


__all__ = ["build_chapter_unit_test_messages"]
