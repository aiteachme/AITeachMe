"""Prompts for chapter-level locked title generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_title_lock_messages(
    *,
    subject: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapter: Mapping[str, Any],
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的 DocGen 章节标题锁定器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
你只能在 confirmed title 的基础上做轻微收束和具体化，不能引入新主题。
""".strip()
    prompt = f"""
请为下面这一章锁定最终发布标题。

主题：{subject}
模式：{digest_mode}
用户提示：{user_prompt or "未提供"}
计划摘要：{plan_summary or "未提供"}
Planner 对话与修改摘要：{docgen_history_brief or "暂无"}

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
4. 不要输出任何教学大纲、检索词、媒体请求或其他字段。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_title_lock",
        inputs={
            "subject": subject,
            "digest_mode": digest_mode,
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "has_history": bool(docgen_history_brief),
        },
        output=messages,
    )


__all__ = ["build_title_lock_messages"]
