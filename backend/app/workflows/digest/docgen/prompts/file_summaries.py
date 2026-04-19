"""Prompts for DocGen file material summaries."""

from __future__ import annotations

from app.workflows.digest.docgen.prompts.tracing import trace_prompt_build

FILE_SUMMARY_CHAPTER_TITLE_BUDGET = 24
FILE_SUMMARY_EXCERPT_BUDGET = 18000


def build_file_summary_messages(
    *,
    filename: str,
    digest_mode: str,
    chapter_titles: list[str],
    excerpt: str,
) -> list[dict[str, str]]:
    # 文件原文只作为 LLM 摘要样本输入；完整内容仍保留在原始资料和分片里。
    prompt = f"""
你是 AITeachMe 的学习资料摘要器。请为 DocGen 写作阶段提取这个文件中最有用的内容。

文件：{filename}
模式：{digest_mode}
目标章节：{"、".join(chapter_titles[:FILE_SUMMARY_CHAPTER_TITLE_BUDGET]) or "未提供"}

文件片段：
{excerpt[:FILE_SUMMARY_EXCERPT_BUDGET]}

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
    messages = [
        {"role": "system", "content": "你只输出合法 JSON。"},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "file_summary",
        inputs={
            "filename": filename,
            "digest_mode": digest_mode,
            "chapter_count": len(chapter_titles),
            "excerpt_chars": len(excerpt),
        },
        output=messages,
    )


__all__ = ["build_file_summary_messages"]
