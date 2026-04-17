"""Prompts for DocGen writing intent inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_intent_messages(
    *,
    subject: str,
    digest_mode: str,
    user_goal: str,
    plan_summary: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    chapter_titles = "、".join(
        str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
        for chapter in chapters[:12]
        if str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
    )
    prompt = f"""
你是 AITeachMe 的 DocGen 写作意图分析器。Planner 已经决定大纲；你只决定文档应该怎样讲。

主题：{subject}
模式：{digest_mode}
用户目标：{user_goal or "未提供"}
计划摘要：{plan_summary or "未提供"}
章节标题：{chapter_titles or "未提供"}
材料画像：{dict(material_profile or {})}

请输出 JSON：
{{
  "document_style": "teaching_notes",
  "depth_level": "compact|standard|deep",
  "explanation_depth": "compact|standard|detailed",
  "example_preference": "few|balanced|many",
  "definition_depth": "minimal|standard|strict",
  "exam_orientation": 0.0,
  "review_orientation": 0.0,
  "chapter_style_hints": {{"1": "..."}},
  "avoid_list": ["..."]
}}

要求：
1. sprint 模式通常 exam_orientation 更高，讲法更短、更题型化。
2. systematic 模式通常 explanation_depth 更深，定义和推理更完整。
3. 不要修改章节数量、顺序或主题。
""".strip()
    return [
        {"role": "system", "content": "你只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_intent_messages"]
