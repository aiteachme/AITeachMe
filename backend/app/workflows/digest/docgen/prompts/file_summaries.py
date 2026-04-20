"""Prompts for DocGen file material summaries."""

from __future__ import annotations

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_file_summary_messages(
    *,
    filename: str,
    digest_mode: str,
    chapter_titles: list[str],
    excerpt: str,
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的学习资料摘要器。
你只输出合法 JSON，不能输出 Markdown、解释或额外文本。
你只能从文件内容中提取对 DocGen 写作有帮助的信息，不能编造文件里没有的内容。
""".strip()
    prompt = f"""
请为 DocGen 写作阶段提取这个文件中最有用的内容。

文件：{filename}
模式：{digest_mode}
目标章节：{"、".join(chapter_titles) or "未提供"}

文件内容：
{excerpt}

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
        {"role": "system", "content": system_prompt},
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
