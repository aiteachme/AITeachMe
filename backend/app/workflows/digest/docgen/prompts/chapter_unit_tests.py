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
每题都有答案、判定依据或解析要点。
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
- items: 数组，每项包含 type、target、stem、answer、basis

题目要求：
1. 每题围绕一个具体知识点、方法步骤、易错边界、图表读取、案例判断或迁移任务。
2. stem、answer、basis 都要短，适合渲染成蜂考式紧凑表格。
3. 题目只围绕本章正文里的知识点、方法和易错边界。
4. 正文已有练习时，改成同知识点的小变式。
5. 只输出 JSON 对象。

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
