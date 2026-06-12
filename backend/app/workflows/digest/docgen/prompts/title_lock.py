"""Prompts for chapter-level locked title generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_title_lock_messages(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的知识文档章节标题锁定器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
根据用户目标、已确认规划、章节目标和必备要点生成最终章节标题。
标题标准：具体、自然、可独立理解，像真实课程目录。
标题聚焦本章知识对象、方法任务、题型技能或应用场景；保留必要限定词。
只在已确认章节语义范围内收束和具体化，不引入新主题。
标题不包含编号、样式说明、宣传话术或抽象标签。
""".strip()
    prompt = f"""
请为下面这一章锁定最终发布标题。

主题：{course_name}
模式：{mode_label}
用户提示：{user_prompt or "未提供"}
Planner plan：{plan or "未提供"}
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
2. 只能做语义范围内的收束、补足和具体化。
3. 如果不确定，enhanced_title 必须直接沿用 confirmed_title。
4. confirmed_title 和 enhanced_title 都只保留语义标题；如果原标题带编号，只保留后面的语义部分。
5. 如果 confirmed_title 偏抽象或像宣传文案，结合 objective / required_elements 写成可理解的课程标题。
6. 如果 title 为空、未命名章节、本章内容或只有“第 N 章”，根据 objective / required_elements 生成真实语义标题。
7. 标题必须让学生不打开正文也知道这一章在讲什么；如果 enhanced_title 离开上下文看不出本章要学什么、做什么或解决什么问题，就不是合格标题。
8. enhanced_title 不设硬字数，但要适合目录扫描。
9. 不输出教学大纲、检索词、媒体请求或其他字段。
10. 如果 enhanced_title 只表达学习阶段或能力目标，而没有写出本章具体内容对象，就不是合格标题。
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
