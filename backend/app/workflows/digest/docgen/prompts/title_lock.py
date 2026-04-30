"""Prompts for chapter-level locked title generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile


def build_title_lock_messages(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的知识文档章节标题锁定器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
你只能在已确认标题的基础上做轻微收束和具体化，不能引入新主题。
标题要像真实课程目录，避免空泛比喻、拟人或文学化表达。
标题自然即可，避免口号化、过度对仗或统一句式。
标题本身不要包含编号或样式说明。
""".strip()
    prompt = f"""
请为下面这一章锁定最终发布标题。

主题：{course_name}
模式：{mode_label}
用户提示：{user_prompt or "未提供"}
计划摘要：{plan_summary or "未提供"}
规划器对话与修改摘要：{docgen_history_brief or "暂无"}

当前章节：
- chapter_index: {chapter.get("chapter_index")}
- title: {chapter.get("title") or chapter.get("resolved_title")}
- objective: {chapter.get("objective")}
- required_elements: {", ".join(str(item) for item in chapter.get("required_elements", []))}

请输出 JSON：
{{
  "chapter_index": 1,
  "confirmed_title": "...",
  "enhanced_title": "...",
  "plan_mismatch_warnings": []
}}

要求：
1. enhanced_title 会成为最终发布标题。
2. 只能做轻微收束、补足和具体化，不能新增学习主题。
3. 如果不确定，enhanced_title 必须直接沿用 confirmed_title。
4. confirmed_title 和 enhanced_title 都只保留语义标题；如果原标题带编号，只保留后面的语义部分。
5. 如果 confirmed_title 偏抽象或像宣传文案，必须结合 objective / required_elements 收束成清晰的课程对象，例如“跨模块联系：代数、几何与统计的综合应用”。
6. 不要为了押韵、对仗或统一句式批量改写标题；相邻章节标题必须各自自然。
7. 不要输出任何教学大纲、检索词、媒体请求或其他字段。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_title_lock",
        inputs={
            "course_name": course_name,
            "digest_mode": digest_mode,
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "has_history": bool(docgen_history_brief),
        },
        output=messages,
    )


__all__ = ["build_title_lock_messages"]
