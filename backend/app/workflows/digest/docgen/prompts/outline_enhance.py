"""Prompts for DocGen execution-level outline enhancement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build

OUTLINE_CHAPTER_REQUIRED_BUDGET = 12


def build_outline_enhance_messages(
    *,
    subject: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
) -> list[dict[str, str]]:
    chapter_lines = []
    # 已确认章节可能很长；这里仅压缩 prompt 摘要，不改变 confirmed plan 本身。
    for chapter in chapters:
        chapter_lines.append(
            "\n".join(
                [
                    f"- chapter_index: {chapter.get('chapter_index')}",
                    f"  title: {chapter.get('title') or chapter.get('resolved_title')}",
                    f"  objective: {chapter.get('objective')}",
                    f"  required_elements: {', '.join(str(item) for item in chapter.get('required_elements', [])[:OUTLINE_CHAPTER_REQUIRED_BUDGET])}",
                ]
            )
        )
    prompt = f"""
你是 AITeachMe 的 DocGen 章节执行大纲设计器。

注意边界：Planner 已经生成并由用户确认了章节计划。你不能新增、删除、重排章节，只能把每章细化成更适合写作的教学执行大纲。
标题是执行合同的一部分：这里输出的 enhanced_title 会成为最终发布标题，后续发布前不会再二次改标题。

主题：{subject}
模式：{digest_mode}
用户提示：{user_prompt or "未提供"}
计划摘要：{plan_summary or "未提供"}
Planner 对话与修改摘要：{docgen_history_brief or "暂无"}

已确认章节：
{chr(10).join(chapter_lines)}

请输出 JSON，格式：
{{
  "chapters": [
    {{
      "chapter_index": 1,
      "confirmed_title": "...",
      "enhanced_title": "...",
      "objective": "...",
      "teaching_outline": ["..."],
      "content_points": ["..."],
      "concept_targets": ["..."],
      "definition_targets": ["..."],
      "formula_targets": ["..."],
      "example_targets": ["..."],
      "pitfall_targets": ["..."],
      "summary_targets": ["..."],
      "media_requests": [{{"kind": "mermaid|interactive", "description": "..."}}],
      "practice_seed_policy": {{"style": "..."}},
      "retrieval_queries": ["..."],
      "plan_mismatch_warnings": []
    }}
  ],
  "plan_mismatch_warnings": []
}}

要求：
1. chapters 数量和 chapter_index 必须与已确认章节完全一致。
2. enhanced_title 是最终标题，必须优先服务用户提示，其次服务已确认计划；只能做收束、补足和轻微具体化，不能引入用户提示和计划之外的新学习主题。
3. 如果不确定标题是否合适，enhanced_title 必须直接沿用 confirmed_title。
4. systematic 偏定义、结构、推理、迁移；sprint 偏考点、题型、速判、易错。
5. 如果某章适合图示，优先输出 mermaid 占位描述；不要主动输出 image 占位。
6. 如果某章涉及公式、推导、证明或计算，优先输出 interactive 占位描述。
7. 所有内容都服务后续写作，不写解释性废话。
""".strip()
    messages = [
        {"role": "system", "content": "你只输出合法 JSON，不输出 Markdown。"},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "outline_enhance",
        inputs={
            "subject": subject,
            "digest_mode": digest_mode,
            "chapter_count": len(chapters),
            "has_history": bool(docgen_history_brief),
        },
        output=messages,
    )


__all__ = ["build_outline_enhance_messages"]
