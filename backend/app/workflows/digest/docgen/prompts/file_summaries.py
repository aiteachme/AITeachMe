"""Prompts for DocGen file material summaries."""

from __future__ import annotations

import json

from app.workflows.digest.common.prompt_tracing import trace_prompt_build
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile


def build_file_summary_messages(
    *,
    filename: str,
    digest_mode: str,
    chapter_titles: list[str],
    excerpt: str,
    section_catalog: list[dict[str, object]] | None = None,
) -> list[dict[str, str]]:
    section_catalog_text = json.dumps(section_catalog or [], ensure_ascii=False, indent=2)
    mode_label = get_docgen_mode_profile(digest_mode).prompt_label
    system_prompt = """
你是 AITeachMe 的学习资料摘要器。
你只输出合法 JSON，不能输出 Markdown、解释或额外文本。
你只能从文件内容中提取对知识文档写作有帮助的信息，不能编造文件里没有的内容。
""".strip()
    prompt = f"""
请为知识文档写作阶段提取这个文件中最有用的内容。

文件：{filename}
模式：{mode_label}
目标章节：{"、".join(chapter_titles) or "未提供"}

切片目录（只能从这里选择 section_ref；line_start/line_end 用于后续精确提取原文）：
{section_catalog_text}

文件内容采样（不是完整全文；切片选择必须以切片目录为准）：
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
  "chapter_slices": [
    {{
      "chapter_index": 1,
      "section_ref": "rf_1_sec_000_xxx",
      "line_start": 12,
      "line_end": 34,
      "relevance": 0.9,
      "usage": "definition|example|formula|pitfall|background",
      "reason": "这段为什么适合该章节",
      "summary": "这段材料可如何进入章节上下文"
    }}
  ],
  "source_quality": 0.7,
  "summary_mode": "llm_sampled"
}}

要求：
1. 只提取对写教学文档有帮助的信息。
2. 章节亲和度用 chapter_index 字符串作为 key。
3. 不要编造文件中没有的真题或引用。
4. `chapter_slices` 是后续写作的关键上下文路由：请基于语义判断每个章节最需要哪些切片，不要只按关键词机械匹配。
5. 每个 `section_ref` 必须来自切片目录；每个文件最多选择 18 个高价值切片，宁缺毋滥。
6. `summary` 要概括这段原文对章节写作的用途，后续会和原文行一起注入章节上下文。
7. 输出必须短：总 `summary` 不超过 180 个中文字符；各列表最多 8 项；每项不超过 32 个中文字符。
8. `chapter_slices` 最多 12 项；`reason` 不超过 50 个中文字符，`summary` 不超过 70 个中文字符。
9. 不要在 `chapter_slices` 里输出 `file_id`、`filename`、`section_title`、`header_path`、`excerpt` 等额外字段。
10. 不确定就跳过；绝不能补造 `????`、省略号或目录中不存在的 `section_ref`。
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
            "section_count": len(section_catalog or []),
        },
        output=messages,
    )


__all__ = ["build_file_summary_messages"]
