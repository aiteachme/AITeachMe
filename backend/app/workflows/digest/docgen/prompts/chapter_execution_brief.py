"""Prompts for chapter-level execution brief generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.workflows.digest.common.prompt_tracing import trace_prompt_build


def build_chapter_execution_brief_messages(
    *,
    subject: str,
    digest_mode: str,
    chapter: Mapping[str, Any],
    locked_title: str,
    intent_core: Mapping[str, Any],
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
) -> list[dict[str, str]]:
    system_prompt = """
你是 AITeachMe 的 DocGen 章节执行 brief 设计器。
你只输出合法 JSON，不输出 Markdown、解释、注释或额外文本。
你的任务是生成“最小可执行脚手架”，不是写完整教学大纲。
""".strip()
    prompt = f"""
请为下面这一章生成简短执行 brief。

主题：{subject}
模式：{digest_mode}
锁定标题：{locked_title}

章节合同：
- chapter_index: {chapter.get("chapter_index")}
- objective: {chapter.get("objective")}
- required_elements: {", ".join(str(item) for item in chapter.get("required_elements", []))}

文档级写作意图：
{dict(intent_core or {})}

骨架线索：
- glossary_terms: {", ".join(str(item) for item in glossary_terms)}
- claim_targets: {", ".join(str(item) for item in claim_targets)}
- confusion_targets: {", ".join(str(item) for item in confusion_targets)}

请输出 JSON：
{{
  "chapter_index": 1,
  "teaching_outline": ["..."],
  "concept_targets": ["..."],
  "definition_targets": ["..."],
  "formula_targets": ["..."],
  "example_targets": ["..."],
  "pitfall_targets": ["..."],
  "retrieval_queries": ["..."],
  "plan_mismatch_warnings": []
}}

要求：
1. 这是最小执行 brief，不是完整教学大纲。
2. `teaching_outline` 最多 3 条。
3. `concept_targets`、`definition_targets`、`formula_targets`、`example_targets`、`pitfall_targets` 各最多 2 条。
4. `retrieval_queries` 最多 2 条。
 5. 不允许顺带修改标题。
 6. 不要输出媒体请求或练习策略，这些后续由规则节点派生。
 7. 只输出简短、可执行的字段，不要输出长段解释。
""".strip()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return trace_prompt_build(
        "chapter_execution_brief",
        inputs={
            "subject": subject,
            "digest_mode": digest_mode,
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "glossary_count": len(list(glossary_terms or [])),
            "claim_target_count": len(list(claim_targets or [])),
        },
        output=messages,
    )


__all__ = ["build_chapter_execution_brief_messages"]
