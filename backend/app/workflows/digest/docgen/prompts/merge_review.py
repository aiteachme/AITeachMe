"""Prompts for whole-document DocGen review."""

from __future__ import annotations


def build_merge_review_messages(*, chapter_summaries: list[str], plan_summary: str) -> list[dict[str, str]]:
    prompt = f"""
请审查这份 AITeachMe 知识文档的整本质量。

计划摘要：{plan_summary or "未提供"}

章节摘要：
{chr(10).join(f"- {item}" for item in chapter_summaries[:20])}

请输出 JSON：
{{
  "passed": true,
  "decision": "publish|publish_with_warnings|fail",
  "issues": [
    {{"severity": "warning", "chapter_index": 1, "issue_type": "coverage", "detail": "...", "suggestion": "..."}}
  ],
  "coverage_summary": {{}},
  "style_summary": {{}},
  "source_summary": {{}}
}}
""".strip()
    return [
        {"role": "system", "content": "你只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_merge_review_messages"]
