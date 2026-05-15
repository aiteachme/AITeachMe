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
你要根据用户目标、已确认规划、章节目标和必备要点，用语义判断生成最终章节标题；不要靠固定关键词、模板短语或本地摘词来命名。
你只能在已确认章节语义范围内收束和具体化，不能引入新主题。
标题要像真实课程目录，让学生不打开正文也知道这一章会学什么、会解决什么问题。
标题不是标签，不要只写抽象分类；自然表达本章的知识对象、方法任务或练习场景。
避免空泛比喻、拟人或文学化表达，也不要为了统一句式批量改写。
标题自然即可，避免口号化、过度对仗或统一句式。
标题本身不要包含编号或样式说明。
风格示例：洛必达法则、等价无穷小替换、分部积分、闭区间最值、矩阵分解。
这些只是长度和清晰度示例，不是候选词表；必须按本章上下文重新命名。
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
2. 只能做语义范围内的收束、补足和具体化，不能新增学习主题。
3. 如果不确定，enhanced_title 必须直接沿用 confirmed_title。
4. confirmed_title 和 enhanced_title 都只保留语义标题；如果原标题带编号，只保留后面的语义部分。
5. 如果 confirmed_title 偏抽象或像宣传文案，必须结合 objective / required_elements 判断本章真实学习任务，再写成人能直接理解的课程标题。
6. 如果 title 为空、未命名章节、本章内容或只有“第 N 章”，必须根据 objective / required_elements 生成真实语义标题，不能输出占位标题。
7. 标题必须让学生不打开正文也知道这一章在讲什么；如果 enhanced_title 离开上下文看不出本章要学什么、做什么或解决什么问题，就不是合格标题。
8. 不要从固定标签、关键词或示例里拼标题；必须基于本章上下文做语义命名。
9. 不要输出任何教学大纲、检索词、媒体请求或其他字段。
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
