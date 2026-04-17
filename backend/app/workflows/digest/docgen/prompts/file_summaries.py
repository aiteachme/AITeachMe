"""Prompts for DocGen file material summaries."""

from __future__ import annotations

from langsmith import traceable


@traceable(name="digest.docgen.file_summary_prompt", run_type="prompt")
def build_file_summary_messages(
    *,
    filename: str,
    digest_mode: str,
    chapter_titles: list[str],
    excerpt: str,
) -> list[dict[str, str]]:
    prompt = f"""
你是 AITeachMe 的学习资料摘要器。请为 DocGen 写作阶段提取这个文件中最有用的内容。

文件：{filename}
模式：{digest_mode}
目标章节：{"、".join(chapter_titles[:12]) or "未提供"}

文件片段：
{excerpt[:18000]}

请输出 JSON：
{{
  "summary": "...",
  "concepts": ["..."],
  "definitions": ["..."],
  "formulas": ["..."],
  "examples": ["..."],
  "question_types": ["..."],
  "high_value_sections": ["..."],
  "noise_sections": ["..."],
  "chapter_affinity": {{"1": 0.8}},
  "source_quality": 0.7,
  "summary_mode": "llm_sampled"
}}

要求：
1. 只提取对写教学文档有帮助的信息。
2. 章节亲和度用 chapter_index 字符串作为 key。
3. 不要编造文件中没有的真题或引用。
""".strip()
    return [
        {"role": "system", "content": "你只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]


__all__ = ["build_file_summary_messages"]
